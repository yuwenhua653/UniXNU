// SPDX-License-Identifier: BSD-2-Clause-Patent
// Adapted from Typeun/myron-device d9b6be4d75f5a8169aee65b02bb23cd88968c1eb.
// Native SM8850/A840 hardware path for the 2 GiB myron iPhone27 port.
// Opt-in myron-gpu=1; no automatic Metal advertisement, panic page or fake fence.
#include <IOKit/IOService.h>
#include <IOKit/IOPlatformExpert.h>
#include <IOKit/IOLib.h>
#include <IOKit/IODeviceMemory.h>
#include <IOKit/IOMemoryDescriptor.h>
#include <IOKit/IOUserClient.h>
#include <kern/thread.h>
#include <kern/debug.h>
#include <kern/clock.h>
#include <pexpert/pexpert.h>
#include <mach/kmod.h>
#include "MyronGpuPolicy.h"
#include "MyronGpuFence.h"
#include "MyronA840RenderConfig.h"
extern "C" {
#include "MyronGpuBoard.h"
#include "MyronGmu.h"
#include "MyronCmdDb.h"
#include "MyronHfi.h"
#include "AdrenoHfi.h"
#include "AdrenoPM4.h"
volatile uint32_t myron_gpu_stage;
volatile uint32_t myron_gpu_ready;
volatile uint32_t myron_gpu_complete;
static uint32_t gpuResult[11];
// Exact OS3.0.306 inputs, checked and embedded by gpu_build.py.
extern const uint8_t myron_gmu_firmware[], myron_sqe_firmware[], myron_aqe_firmware[], myron_zap_firmware[];
extern const uint64_t myron_gmu_firmware_size, myron_sqe_firmware_size, myron_aqe_firmware_size, myron_zap_firmware_size;
// NativeAdrenoPublish.cpp hands user space's boot-log export to this hook (sheng's BootLog.c keeps it); myron has no log
// export, so it refuses every piece. A definition is required: the kernel's static link resolves no weak import.
int boot_log_export_put(uint32_t, uint32_t, uint32_t, const void *, uint32_t) {return -1;}
// NativeAdreno's BO pool (NativeAdrenoMemory.cpp): the size the board asks for, the reservation's status, and [0] pool MiB, [1] BOs
// from the pool, [2] BOs that fell back, [3] MiB in use, [4] peak MiB, [5] scattered BOs, [6] their spans, [7] import spans.
extern volatile uint32_t native_adreno_pool_mib, native_adreno_pool_status, native_adreno_pool_stats[8];
}
#include "MyronA840HwInit.h"
#include "NativeAdrenoGmuContext.h"
#include "NativeAdrenoGpuContext.h"
#include "NativeAdrenoCpInit.h"
#include "NativeAdrenoTimer.h"
#include "NativeAdrenoSubmit.h"
#include "NativeAdrenoUserClient.h"
#include "NativeAdrenoMemory.h"
extern "C" { extern volatile uint32_t native_adreno_io_coherent; extern volatile uint32_t native_adreno_flush_imports; }
extern "C" IOReturn native_adreno_publish(NativeAdrenoVm *, NativeAdrenoSubmit *, NativeAdrenoRing *, const NativeAdrenoRingClock *,
    const NativeAdrenoTimer *, const NativeAdrenoAbiDeviceInfo *, uint32_t, uint32_t);
extern "C" IOService *native_adreno_published_service();
extern "C" uint32_t native_adreno_publish_stats(uint32_t *closed);
namespace {
struct Window {uint64_t phys, length; IOMemoryMap *map; uintptr_t va;};

Window gWindows[MG_WINDOWS] = {
    {MG_GCC_GPU_PAGE, 0x1000, nullptr, 0},
    {MG_GCC_VOTE_PAGE, 0x1000, nullptr, 0},
    {MG_GPUCC_BASE, MG_GPUCC_SIZE, nullptr, 0},
    {MG_GXCC_PAGE, 0x1000, nullptr, 0},
    {MG_SMMU_BASE, MG_SMMU_GR0_SIZE, nullptr, 0},
    {MG_GMU_PAGE, MG_GMU_WINDOW, nullptr, 0},
    {MG_GPU_BASE, MG_GPU_WINDOW, nullptr, 0},
};
Window gGmuWindows[MGM_WINDOWS] = {
    {MGM_GMU_BASE, MGM_GMU_SIZE, nullptr, 0},
    {MGM_RSCC_BASE, MGM_RSCC_SIZE, nullptr, 0},
    {MGM_GPU_BASE, MGM_GPU_SIZE, nullptr, 0},
    {MGM_CXMISC_BASE, MGM_CXMISC_SIZE, nullptr, 0},
};

uintptr_t mapOne(Window &w, IOOptionBits cache) {
    IODeviceMemory *memory = IODeviceMemory::withRange(w.phys, w.length);
    if (!memory) return 0;
    w.map = memory->map(kIOMapAnywhere | cache);
    memory->release();
    w.va = w.map ? static_cast<uintptr_t>(w.map->getVirtualAddress()) : 0;
    return w.va;
}
// Mapping a window reads nothing; a block is only touched once its prerequisites read on.
unsigned mapWindows(Window *windows, unsigned count) {
    unsigned have = 0;
    for (unsigned i = 0; i < count; ++i) if (mapOne(windows[i], kIOMapInhibitCache)) have |= 1u << i;
    return have;
}

int mmio(Window *windows, unsigned count, unsigned base, unsigned window, uint32_t offset, uint32_t *out, const uint32_t *in) {
    if (window >= count || !windows[window].va || offset + 4 > windows[window].length || (offset & 3)) return -1;
    __atomic_store_n(&myron_gpu_stage,(base + window + 1) << 24 | offset | (in ? 1u << 23 : 0),__ATOMIC_RELAXED);   // a faulting access leaves itself here
    volatile uint32_t *reg = reinterpret_cast<volatile uint32_t *>(windows[window].va + offset);
    if (in) {*reg = *in; __asm__ volatile("dsb sy" ::: "memory");}
    else *out = *reg;
    return 0;
}
int rd(void *, unsigned window, uint32_t offset, uint32_t *out) {return mmio(gWindows, MG_WINDOWS, 0, window, offset, out, nullptr);}
int wr(void *, unsigned window, uint32_t offset, uint32_t value) {return mmio(gWindows, MG_WINDOWS, 0, window, offset, nullptr, &value);}
int grd(void *, unsigned window, uint32_t offset, uint32_t *out) {return mmio(gGmuWindows, MGM_WINDOWS, 8, window, offset, out, nullptr);}
int gwr(void *, unsigned window, uint32_t offset, uint32_t value) {return mmio(gGmuWindows, MGM_WINDOWS, 8, window, offset, nullptr, &value);}
void delayUs(void *, unsigned us) {IODelay(us);}
void barrier(void *) {__asm__ volatile("dsb sy" ::: "memory");}

// SIP SMC as qcom_scm-smc.c makes it (sheng's scmCall): x0 function, x1 arginfo, x2.. arguments; QCOM_SCM_INTERRUPTED (1)
// resumes with x0 = 1 and the returned x6, QCOM_SCM_V2_EBUSY (-12) retries after 30 ms, at most 20 times.
struct ScmRes {int64_t a0; uint64_t a1; unsigned resumes;};
ScmRes scmCall(uint64_t fn, uint64_t arginfo, uint64_t p0, uint64_t p1 = 0, uint64_t p2 = 0) {
    uint64_t first = fn, a6 = 0;
    unsigned resume = 0, busy = 0;
    while (resume < 10000) {
        register uint64_t x0 asm("x0") = first, x1 asm("x1") = arginfo, x2 asm("x2") = p0, x3 asm("x3") = p1;
        register uint64_t x4 asm("x4") = p2, x5 asm("x5") = 0, x6 asm("x6") = a6, x7 asm("x7") = 0;
        asm volatile("smc #0" : "+r"(x0), "+r"(x1), "+r"(x2), "+r"(x3), "+r"(x4), "+r"(x5), "+r"(x6), "+r"(x7)
                     :: "x8", "x9", "x10", "x11", "x12", "x13", "x14", "x15", "x16", "x17", "memory");
        if (x0 == 1) {first = 1; a6 = x6; ++resume; continue;}
        if (int64_t(x0) == -12 && busy++ < 20) {first = fn; a6 = 0; IOSleep(30); continue;}
        return {int64_t(x0), x1, resume};
    }
    return {-1000, 0, resume};
}
// ARM_SMCCC_CALL_VAL(STD, SMC_64, OWNER_SIP, QCOM_SCM_SVC_GPU 0x28 << 8 | QCOM_SCM_SVC_GPU_INIT_REGS 0x1); one value argument,
// QCOM_SCM_GPU_ALWAYS_EN_REQ | QCOM_SCM_GPU_TSENSE_EN_REQ.
constexpr uint64_t kScmGpuInitRegs = 0x42000000u | (0x28u << 8) | 0x01u;
constexpr uint64_t kGpuInitRegsArg = (1u << 0) | (1u << 3);

// The GMU's SMMU context: bank 1 / ASID 1 / SMR+S2CR slot 2 as on sheng; stream 5 from myron's gmu iommus.
constexpr unsigned kGmuBank = 1, kGmuAsid = 1, kGmuSlot = 2, kGmuSid = 5;
constexpr uint64_t kSmmuWindow = 0x40000;   // kgsl-smmu@3da0000 reg size: global spaces and 21 context banks

struct Mode4 {
    ScmRes scm;
    mg_gmu_clocks clocks;
    uint32_t smr[4], s2cr[4];
    uint32_t pwr_clk, rpmh, sysreset, fw_init, hfi, ao_count, version, rsc_status, seq_busy, rscc_ack, tcm_ret, ao_status;
    unsigned gmu_have;
    mcd_result db;
    uint16_t gfx[16], mx[16], cx[16], gmxc[16];
    unsigned gfx_n, mx_n, cx_n, gmxc_n;
    int db_mapped;
};
struct Mode5 {
    int ran, s2cr_fixed;
    uint32_t s2cr_before;
    NativeAdrenoGmuContextReport ctx;
    IOReturn ctx_status, payload_status;
    NativeAdrenoGmuPayload payloads[5];
    unsigned payload_maps;
    mgm_result gmu;
};
struct Mode6 {
    int ran;
    unsigned step;                       // 1 tables, 2 perf, 3 bw, 4 core start, 5 start, 6 GX vote, 7 OOB, 8 GX wait, 9 GX on
    unsigned sent;                       // bit per message slot that was sent
    mhf_tables t;
    AdrenoHfiStatus hs[5];
    uint32_t fw_error[5];
    size_t reply_words[5];
    int oob_ok;
    uint32_t oob_info, pwr_before, pwr_after, rpmh, gx_gdscr, gx_cfg, rbbm, rbbm_gfx, gbif_halt;
    unsigned oob_polls, gx_polls;
};
// Mode 7 (register init, no GPU memory).
struct Mode7 {
    int ran;
    unsigned writes, io_errors;          // GPU register writes made, accesses refused by the window check
    uint32_t gbif_halt, rbbm_gbif_halt;  // the read-backs hw_init makes after releasing the halts
    unsigned checked, matched;           // written registers read back / equal to what was written
    uint32_t bad_reg, bad_got, bad_want; // the first that differs: dword offset | pipe << 20
    uint32_t bad2_reg, bad2_got, bad2_want;   // and the second
    uint32_t status, int0, cp_int;       // RBBM_STATUS, RBBM_INT_0_STATUS, CP_INTERRUPT_STATUS_GLOBAL afterwards
    uint32_t fuse_freq, fuse_value, slices;   // CX_MISC SW_FUSE_FREQ_LIMIT_STATUS, SW_FUSE_VALUE, SLICE_ENABLE_FINAL
};
// Mode 8 (command processor).
struct Mode8 {
    int ran;
    unsigned step;   // 1 stream slots, 2 context, 3 buffers, 4 SQE buffer, 5 microcode, 6 ring + SQE start, 7 CP init sent,
                     // 8 CP init consumed, 9 mem write sent, 10 mem write and fence seen
    uint32_t s2cr_before[2];
    unsigned s2cr_fixed, views;
    NativeAdrenoGmuContextReport ctx;
    IOReturn ctx_status, buf_status, sqe_alloc, sqe_map;
    NativeAdrenoGpuBuffer buf[5];
    uint64_t sqe_phys;
    uint32_t sqe_bad, aqe_bad;           // first differing byte + 1 of the microcode read back
    uint32_t actlr, actlr_set;           // context bank 0 ACTLR as found, and read back after myron-gpu-actlr
    uint32_t rptr0, wptr0, wptr;
    unsigned init_polls, fence_polls;
    int init_idle;
    uint32_t rptr, shadow, bv_rptr, status, int0, cp_int, pipe_int, hw_fault, sqe_status, protect_status;
    uint32_t fence, scratch, scratch_reg;
    uint32_t fsr, far_lo, far_hi, fsynr0, gfsr;
};
// Mode 9 (zap shader and secure-mode exit).
struct Mode9 {
    int ran, stage;  // as sheng's zapAndSecure: <0 refused at that check; 3 init_image, 4 mem_setup, 5 copy, 6 auth, 7 secure
                     // fence, 8 second write, 9 done
    int64_t init, mem, auth;
    unsigned resumes[3], polls, polls2;
    uint32_t fence, scratch, status, int0, cp_int, fsr;
};
Mode4 gM4;
Mode5 gM5;
Mode6 gM6;
Mode7 gM7;
Mode8 gM8;
Mode9 gM9;
Window gSmmu = {MG_SMMU_BASE, kSmmuWindow, nullptr, 0};   // the whole kgsl-smmu window, mapped by mode 5
alignas(8) uint8_t gCmdDb[MCD_BYTES];
AdrenoHfi gHfi;

int hfiNotify(void *) {
    uint32_t one = 1;
    return mmio(gGmuWindows, MGM_WINDOWS, 8, MGM_WIN_GMU, MGM_GMU(MGM_HOST2GMU_INTR_SET), nullptr, &one);
}
int hfiInit(void *, volatile uint32_t *shared, uint32_t bytes, uint32_t iova) {
    return AdrenoHfiInitializeStopped(&gHfi, shared, bytes, iova, nullptr, hfiNotify) != AdrenoHfiSuccess;
}

void mode4(const mg_io &io, mg_result &r, unsigned have) {
    Mode4 &m = gM4;
    mg_gmu_clocks_on(&io, &r, &m.clocks);
    if (m.clocks.step != 7 || m.clocks.failed || r.io_error) return;
    m.scm = scmCall(kScmGpuInitRegs, 1, kGpuInitRegsArg);   // after the clocks, as a6xx_gmu_resume orders them
    if (m.scm.a0 || m.scm.a1) return;
    if (have & (1u << MG_WIN_SMMU) && r.smmu == MG_DONE)
        for (unsigned i = 0; i < 4; ++i) {rd(nullptr, MG_WIN_SMMU, MG_SMMU_SMR(i), &m.smr[i]); rd(nullptr, MG_WIN_SMMU, MG_SMMU_S2CR(i), &m.s2cr[i]);}
    m.gmu_have = mapWindows(gGmuWindows, MGM_WINDOWS);
    if (m.clocks.step == 7 && m.gmu_have == (1u << MGM_WINDOWS) - 1) {
        grd(nullptr, MGM_WIN_GMU, MGM_GMU(MGM_PWR_CLK_STATUS), &m.pwr_clk);
        grd(nullptr, MGM_WIN_GMU, MGM_GMU(MGM_PWR_CLK_STATUS + 1), &m.rpmh);
        grd(nullptr, MGM_WIN_GMU, MGM_GMU(MGM_CM3_SYSRESET), &m.sysreset);
        grd(nullptr, MGM_WIN_GMU, MGM_GMU(MGM_CM3_FW_INIT_RESULT), &m.fw_init);
        grd(nullptr, MGM_WIN_GMU, MGM_GMU(MGM_HFI_CTRL_STATUS), &m.hfi);
        grd(nullptr, MGM_WIN_GMU, MGM_GMU(0x1f840), &m.ao_count);
        grd(nullptr, MGM_WIN_GMU, MGM_GMU(MGM_CM3_DTCM_START + 0xff8), &m.version);
        grd(nullptr, MGM_WIN_GMU, MGM_GMU(MGM_RSCC_CONTROL_ACK), &m.rscc_ack);
        grd(nullptr, MGM_WIN_GMU, MGM_GMU(MGM_AO_HOST_INTERRUPT_STATUS), &m.ao_status);
        grd(nullptr, MGM_WIN_RSCC, MGM_RSC_STATUS0, &m.rsc_status);
        grd(nullptr, MGM_WIN_RSCC, MGM_RSCC_SEQ_BUSY, &m.seq_busy);
        grd(nullptr, MGM_WIN_CXMISC, MGM_CX_TCM_RET_CNTL, &m.tcm_ret);
    }
    // The command DB is ordinary memory the AOP filled; it is copied with aligned word reads.
    Window db = {MCD_BASE, MCD_BYTES, nullptr, 0};
    if (mapOne(db, kIOMapInhibitCache)) {
        m.db_mapped = 1;
        const volatile uint32_t *src = reinterpret_cast<const volatile uint32_t *>(db.va);
        uint32_t *dst = reinterpret_cast<uint32_t *>(gCmdDb);
        for (uint32_t i = 0; i < MCD_BYTES / 4; ++i) dst[i] = src[i];
        mcd_parse(gCmdDb, MCD_BYTES, &m.db);
        m.gfx_n = mcd_arc_levels(&m.db.r[MCD_GFX], m.gfx, 16);
        m.mx_n = mcd_arc_levels(&m.db.r[MCD_MX], m.mx, 16);
        m.cx_n = mcd_arc_levels(&m.db.r[MCD_CX], m.cx, 16);
        m.gmxc_n = mcd_arc_levels(&m.db.r[MCD_GMXC], m.gmxc, 16);
    }
}

void gmuProgress(uint32_t step) {myron_gpu_stage = 0x50000000u | step;}

int hfiWaitOnce(void *) {IODelay(100); return 0;}
// One HFI command and its acknowledgement through the kit (as a6xx_hfi_send_msg / a6xx_hfi_wait_for_ack: 1 s), then the
// message-queue interrupt bit cleared as a6xx_hfi_wait_for_ack clears it.
bool exchange(unsigned slot, unsigned id, const uint32_t *payload, size_t words) {
    Mode6 &m = gM6;
    uint32_t reply[16];
    myron_gpu_stage = 0x60000000u | id << 8 | slot;
    m.sent |= 1u << slot;
    m.hs[slot] = AdrenoHfiExchange(&gHfi, id, payload, words, 10000, hfiWaitOnce, reply, 16, &m.reply_words[slot], &m.fw_error[slot]);
    gwr(nullptr, MGM_WIN_GMU, MGM_GMU(MGM_GMU2HOST_INTR_CLR), 1);
    return m.hs[slot] == AdrenoHfiSuccess;
}

void mode6() {
    Mode6 &m = gM6;
    if (!gM5.ran || gM5.ctx_status || gM5.payload_status || gM5.payload_maps != 5 ||
        gM5.gmu.phase != 8 || gM5.gmu.status != MGM_OK) return;
    m.ran = 1;
    m.step = 1;
    if (mhf_build(&gM4.db, &m.t)) return;
    m.step = 2;
    if (!exchange(0, MHF_MSG_TABLE, m.t.perf, m.t.perf_words)) return;
    m.step = 3;
    if (!exchange(1, MHF_MSG_BW_TABLE, m.t.bw, MHF_BW_WORDS)) return;
    m.step = 4;
    static const uint32_t handle = 0;
    if (!exchange(2, MHF_MSG_CORE_FW_START, &handle, 1)) return;
    m.step = 5;
    if (!exchange(3, MHF_MSG_START, nullptr, 0)) return;
    // The rest of a6xx_gmu_resume after a6xx_hfi_start: the CM3 fault interrupt unmasked (the line itself stays off in the
    // GIC), then a6xx_gmu_set_initial_freq, whose a6xx_hfi_set_freq votes GX: GX_BW_PERF_VOTE {ack_type 1 (blocking), perf
    // index, bandwidth index}. The OOB below comes later in Linux, from hw_init; the GMU acknowledges it only after this vote
    // (myron-gpu=6 of 2026-10-22 asked first and got no acknowledgement).
    gwr(nullptr, MGM_WIN_GMU, MGM_GMU(MGM_GMU2HOST_INTR_CLR), 0xffffffffu);
    gwr(nullptr, MGM_WIN_GMU, MGM_GMU(MGM_GMU2HOST_INTR_MASK), ~MGM_CM3_FAULT);
    m.step = 6;
    grd(nullptr, MGM_WIN_GMU, MGM_GMU(MGM_PWR_CLK_STATUS), &m.pwr_before);
    unsigned perf = MYRON_GPU_BOOT_PERF;
    PE_parse_boot_argn("myron-gpu-perf", &perf, sizeof perf);
    m.t.perf_index = myron_gpu_perf_level(perf, m.t.perf_index);
    if (!m.t.perf_index) return;
    m.t.bw_index = mhf_gpu_levels[m.t.perf_index].bw;
    const uint32_t vote[3] = {1, m.t.perf_index, m.t.bw_index};
    if (!exchange(4, MHF_MSG_GX_BW_PERF_VOTE, vote, 3)) return;
    // hw_init's a6xx_gmu_set_oob(GMU_OOB_GPU_SET), non-legacy bits: request 30, acknowledgement 31 (100 us steps; Linux waits
    // 10 ms, this waits up to 100 ms and records how long it took).
    m.step = 7;
    gwr(nullptr, MGM_WIN_GMU, MGM_GMU(MGM_HOST2GMU_INTR_SET), 1u << 30);
    for (;;) {
        ++m.oob_polls;
        grd(nullptr, MGM_WIN_GMU, MGM_GMU(MGM_GMU2HOST_INTR_INFO), &m.oob_info);
        if (m.oob_info & (1u << 31)) break;
        if (m.oob_polls >= 1000) {grd(nullptr, MGM_WIN_GMU, MGM_GMU(MGM_PWR_CLK_STATUS), &m.pwr_after); return;}
        IODelay(100);
    }
    gwr(nullptr, MGM_WIN_GMU, MGM_GMU(MGM_GMU2HOST_INTR_CLR), 1u << 31);
    m.oob_ok = 1;
    // a8xx_gmu_gx_is_on: neither GX_HM_GDSC_POWER_OFF nor GX_HM_CLK_OFF (bits 0 and 1); up to 100 ms.
    m.step = 8;
    for (;;) {
        ++m.gx_polls;
        grd(nullptr, MGM_WIN_GMU, MGM_GMU(MGM_PWR_CLK_STATUS), &m.pwr_after);
        if (!(m.pwr_after & 3)) break;
        if (m.gx_polls >= 1000) break;
        IODelay(100);
    }
    grd(nullptr, MGM_WIN_GMU, MGM_GMU(MGM_PWR_CLK_STATUS + 1), &m.rpmh);
    rd(nullptr, MG_WIN_GXCC, MG_GX_GDSCR, &m.gx_gdscr);
    rd(nullptr, MG_WIN_GXCC, MG_GX_CFG_GDSCR, &m.gx_cfg);
    if (m.pwr_after & 3) return;
    // GX is up and held by the OOB: the GPU block's own status words (gen8_reg.h, dwords from the GPU base).
    m.step = 9;
    grd(nullptr, MGM_WIN_GPU, MG_RBBM_STATUS, &m.rbbm);
    grd(nullptr, MGM_WIN_GPU, MG_RBBM_GFX_STATUS, &m.rbbm_gfx);
    grd(nullptr, MGM_WIN_GPU, MG_RBBM_GBIF_HALT, &m.gbif_halt);
}

void mode5(mg_result &r) {
    Mode5 &m = gM5;
    const Mode4 &p = gM4;
    // The context needs CX, the SMMU vote clock and the GMU clocks running, an SMMU with no stream mapped, and the GMU
    // stopped; every condition is the reading of this same boot.
    if (r.smmu != MG_DONE || r.smr_valid || p.clocks.step != 7 || p.gmu_have != (1u << MGM_WINDOWS) - 1 || p.sysreset != 1) return;
    m.ran = 1;
    Window &smmu = gSmmu;
    if (!mapOne(smmu, kIOMapInhibitCache)) {m.ctx_status = kIOReturnNoMemory; return;}
    // The kit attaches only to a slot whose S2CR faults; an unused slot (SMR invalid) is set to FAULT first.
    volatile uint32_t *s2cr = reinterpret_cast<volatile uint32_t *>(smmu.va + MG_SMMU_S2CR(kGmuSlot));
    m.s2cr_before = *s2cr;
    if (((m.s2cr_before >> 16) & 3) != 2 && !(p.smr[kGmuSlot] & (1u << 31))) {
        *s2cr = 0x20000;
        __asm__ volatile("dsb sy" ::: "memory");
        m.s2cr_fixed = 1;
    }
    m.ctx_status = NativeAdrenoGmuContextBringup(reinterpret_cast<volatile uint8_t *>(smmu.va), kSmmuWindow, kGmuBank, kGmuAsid,
                                                 kGmuSlot, kGmuSid, gmuProgress, &m.ctx);
    if (m.ctx_status) return;
    m.payload_status = NativeAdrenoGmuContextPayloads(m.payloads);
    if (m.payload_status) return;
    // The GMU maps its buffers Normal non-cacheable; the CPU gets a write-combined view of each.
    mgm_memory memory[5] = {};
    static Window views[5];
    for (unsigned i = 0; i < 5; ++i) {
        views[i] = {m.payloads[i].physical, m.payloads[i].bytes, nullptr, 0};
        if (!mapOne(views[i], kIOMapWriteCombineCache)) return;
        ++m.payload_maps;
        memory[i] = {reinterpret_cast<volatile uint32_t *>(views[i].va), uint32_t(m.payloads[i].bytes), uint32_t(m.payloads[i].iova)};
    }
    mgm_io io = {nullptr, grd, gwr, barrier, delayUs};
    mgm_config config = {myron_gmu_firmware, size_t(myron_gmu_firmware_size), memory[0], memory[1], memory[2], memory[3], memory[4],
                         hfiInit, nullptr};
    myron_gpu_stage = 0x51000000u;
    mgm_cold_start(&io, &config, &m.gmu);
}

// GPU registers through the cold-start GPU window (dword offsets of MyronA840HwInit.h). Pipe registers are reached through
// CP_APERTURE_CNTL_HOST, as a8xx_write_pipe / a8xx_read_pipe_slice do (slice 0).
uint32_t gpuRd(uint32_t reg) {
    uint32_t v = 0xdeadbeef;
    if (grd(nullptr, MGM_WIN_GPU, reg * 4, &v)) ++gM7.io_errors;
    return v;
}
void gpuWr(uint32_t reg, uint32_t value) {
    ++gM7.writes;
    if (gwr(nullptr, MGM_WIN_GPU, reg * 4, value)) ++gM7.io_errors;
}
void gpuWr64(uint32_t reg, uint64_t value) {gpuWr(reg, uint32_t(value)); gpuWr(reg + 1, uint32_t(value >> 32));}
void aperture(unsigned pipe) {gpuWr(A840_CP_APERTURE_CNTL_HOST, A840_APERTURE_PIPE(pipe));}
void pipeWr(unsigned pipe, uint32_t reg, uint32_t value) {aperture(pipe); gpuWr(reg, value);}
uint32_t pipeRd(unsigned pipe, uint32_t reg) {aperture(pipe); return gpuRd(reg);}

// Mode 7. a8xx_gpu.c hw_init from after a6xx_gmu_set_oob(GPU_SET) to just before adreno_hw_init, line for line. Left out:
// the GMU power and busy counter selects and, later, hwcg (no A840 table in
// Linux). Rendering state uses the SM8850 KGSL UBWC6 and bicubic configuration.
constexpr uint64_t kGmemRangeMin = 0x4000000;            // SZ_64M
constexpr uint64_t kUcheTrapBase = 0x1fffffffff000ull;   // a6xx_gpu_init's uche_trap_base for A7XX and later
void mode7() {
    Mode7 &m = gM7;
    if (gM6.step != 9 || (gM6.pwr_after & 3)) return;
    m.ran = 1;
    aperture(A840_PIPE_NONE);
    gpuWr(A840_GBIF_HALT, 0);
    m.gbif_halt = gpuRd(A840_GBIF_HALT);
    gpuWr(A840_RBBM_GBIF_HALT, 0);
    m.rbbm_gbif_halt = gpuRd(A840_RBBM_GBIF_HALT);
    gpuWr(A840_RBBM_SECVID_TSB_CNTL, 0);
    gpuWr64(A840_RBBM_SECVID_TSB_TRUSTED_BASE, 0);
    gpuWr(A840_RBBM_SECVID_TSB_TRUSTED_SIZE, 0);
    gpuWr(A840_RBBM_PERFCTR_GPU_BUSY_MASKED, 0xffffffffu);
    gpuWr64(A840_UCHE_CCHE_GC_GMEM_RANGE_MIN, kGmemRangeMin);
    gpuWr64(A840_SP_HLSQ_GC_GMEM_RANGE_MIN, kGmemRangeMin);
    gpuWr64(A840_UCHE_TRAP_BASE, kUcheTrapBase);
    gpuWr64(A840_UCHE_WRITE_THRU_BASE, kUcheTrapBase);
    gpuWr64(A840_UCHE_CCHE_TRAP_BASE, kUcheTrapBase);
    gpuWr64(A840_UCHE_CCHE_WRITE_THRU_BASE, kUcheTrapBase);
    gpuWr(A840_RBBM_PERFCTR_CNTL, 1);
    gpuWr(A840_RBBM_SLICE_PERFCTR_CNTL, 1);
    gpuWr(A840_CP_PERFCTR_CP_SEL(0), 1);
    // a8xx_set_ubwc_config (kaanapali: UBWC 6.0, highest bank bit 16).
    pipeWr(A840_PIPE_BV, A840_GRAS_NC_MODE_CNTL, A840_UBWC_GRAS_NC_MODE_CNTL);
    pipeWr(A840_PIPE_BR, A840_GRAS_NC_MODE_CNTL, A840_UBWC_GRAS_NC_MODE_CNTL);
    pipeWr(A840_PIPE_BR, A840_RB_CCU_NC_MODE_CNTL, A840_UBWC_RB_CCU_NC_MODE_CNTL);
    pipeWr(A840_PIPE_BR, A840_RB_CMP_NC_MODE_CNTL, MYRON_A840_RB_CMP_UBWC6);
    aperture(A840_PIPE_NONE);
    gpuWr(A840_SP_NC_MODE_CNTL, A840_UBWC_SP_NC_MODE_CNTL);
    gpuWr(A840_TPL1_NC_MODE_CNTL, A840_UBWC_TPL1_NC_MODE_CNTL);
    for(unsigned i=0;i<20;++i)gpuWr(MYRON_A840_BICUBIC_BASE+i,MyronA840Bicubic[i]);
    gpuWr(A840_UCHE_CLIENT_PF, (1u << 7) | 0x1);
    // a8xx_nonctxt_config: every pipe from NONE to DDE_BV but LPAC, each entry on the pipes its mask names.
    for (unsigned pipe = A840_PIPE_NONE; pipe <= A840_PIPE_DDE_BV; ++pipe) {
        if (pipe == A840_PIPE_LPAC) continue;
        aperture(pipe);
        for (unsigned i = 0; i < MYRON_A840_NONCTXT_COUNT; ++i)
            if (MyronA840Nonctxt[i][2] & (1u << pipe)) gpuWr(MyronA840Nonctxt[i][0], MyronA840Nonctxt[i][1]);
    }
    aperture(A840_PIPE_NONE);
    gpuWr(A840_RBBM_INTERFACE_HANG_INT_CNTL, (1u << 30) | 0xcfffff);
    gpuWr(A840_RBBM_SLICE_INTERFACE_HANG_INT_CNTL, 1u << 30);
    // a8xx_set_cp_protect.
    pipeWr(A840_PIPE_BR, A840_CP_PROTECT_CNTL_PIPE, MYRON_A8XX_CP_PROTECT_CNTL);
    pipeWr(A840_PIPE_BV, A840_CP_PROTECT_CNTL_PIPE, MYRON_A8XX_CP_PROTECT_CNTL);
    aperture(A840_PIPE_NONE);
    uint32_t final_cfg = 0;
    for (unsigned i = 0; i < MYRON_A840_PROTECT_COUNT; ++i)
        if (MyronA840Protect[i]) {gpuWr(A840_CP_PROTECT_GLOBAL(i), MyronA840Protect[i]); final_cfg = MyronA840Protect[i];}
    pipeWr(A840_PIPE_BR, A840_CP_PROTECT_PIPE(15), final_cfg);
    pipeWr(A840_PIPE_BV, A840_CP_PROTECT_PIPE(15), final_cfg);
    aperture(A840_PIPE_NONE);
    pipeWr(A840_PIPE_BR, A840_RB_CONTEXT_SWITCH_GMEM_SAVE_RESTORE_ENABLE, 1);
    for (unsigned pipe = A840_PIPE_BR; pipe <= A840_PIPE_DDE_BV; ++pipe) {
        if (pipe == A840_PIPE_LPAC) continue;
        aperture(pipe);
        gpuWr(A840_CP_APRIV_CNTL_PIPE, pipe == A840_PIPE_BR ? MYRON_A8XX_BR_APRIV_MASK : MYRON_A8XX_APRIV_MASK);
        gpuWr(A840_CP_INTERRUPT_STATUS_MASK_PIPE, MYRON_A8XX_CP_INTERRUPT_STATUS_MASK_PIPE);
        gpuWr(A840_CP_HW_FAULT_STATUS_MASK_PIPE, MYRON_A8XX_CP_HW_FAULT_STATUS_MASK_PIPE);
    }
    aperture(A840_PIPE_NONE);
    // The masks only reach the GIC through SPI 300, which nothing has enabled: the status words below are polled.
    gpuWr(A840_CP_INTERRUPT_STATUS_MASK_GLOBAL, MYRON_A8XX_CP_GLOBAL_INT_MASK);
    gpuWr(A840_RBBM_INT_0_MASK, 0);
    // Read back what was written, the protect table and the interrupt masks first; the non-context list last, since a
    // chicken bit may read back differently.
    auto check = [&](unsigned pipe, uint32_t reg, uint32_t want) {
        const uint32_t got = pipeRd(pipe, reg);
        ++m.checked;
        if (got == want) ++m.matched;
        else if (!m.bad_reg) {m.bad_reg = reg | pipe << 20; m.bad_got = got; m.bad_want = want;}
        else if (!m.bad2_reg) {m.bad2_reg = reg | pipe << 20; m.bad2_got = got; m.bad2_want = want;}
    };
    for (unsigned i = 0; i < MYRON_A840_PROTECT_COUNT; ++i) check(A840_PIPE_NONE, A840_CP_PROTECT_GLOBAL(i), MyronA840Protect[i]);
    check(A840_PIPE_NONE, A840_RBBM_INT_0_MASK, 0);
    check(A840_PIPE_NONE, A840_CP_INTERRUPT_STATUS_MASK_GLOBAL, MYRON_A8XX_CP_GLOBAL_INT_MASK);
    check(A840_PIPE_NONE, A840_RBBM_PERFCTR_GPU_BUSY_MASKED, 0xffffffffu);
    check(A840_PIPE_NONE, A840_UCHE_TRAP_BASE, uint32_t(kUcheTrapBase));
    check(A840_PIPE_NONE, A840_UCHE_TRAP_BASE + 1, uint32_t(kUcheTrapBase >> 32));
    check(A840_PIPE_NONE, A840_UCHE_CCHE_GC_GMEM_RANGE_MIN, uint32_t(kGmemRangeMin));
    check(A840_PIPE_NONE, A840_UCHE_CLIENT_PF, (1u << 7) | 0x1);
    check(A840_PIPE_NONE, A840_SP_NC_MODE_CNTL, A840_UBWC_SP_NC_MODE_CNTL);
    check(A840_PIPE_NONE, A840_TPL1_NC_MODE_CNTL, A840_UBWC_TPL1_NC_MODE_CNTL);
    check(A840_PIPE_BR, A840_CP_PROTECT_CNTL_PIPE, MYRON_A8XX_CP_PROTECT_CNTL);
    check(A840_PIPE_BR, A840_CP_PROTECT_PIPE(15), final_cfg);
    check(A840_PIPE_BR, A840_CP_APRIV_CNTL_PIPE, MYRON_A8XX_BR_APRIV_MASK);
    check(A840_PIPE_BV, A840_CP_APRIV_CNTL_PIPE, MYRON_A8XX_APRIV_MASK);
    check(A840_PIPE_BR, A840_GRAS_NC_MODE_CNTL, A840_UBWC_GRAS_NC_MODE_CNTL);
    check(A840_PIPE_BR, A840_RB_CCU_NC_MODE_CNTL, A840_UBWC_RB_CCU_NC_MODE_CNTL);
    check(A840_PIPE_BR, A840_RB_CMP_NC_MODE_CNTL, MYRON_A840_RB_CMP_UBWC6);
    for (unsigned i = 0; i < MYRON_A840_NONCTXT_COUNT; ++i) {
        // hw_init rewrites the hang-detect word below the list, and GMEM protection holds only after the secure exit.
        const uint32_t pipes = MyronA840Nonctxt[i][2], reg = MyronA840Nonctxt[i][0];
        if (reg == A840_RBBM_INTERFACE_HANG_INT_CNTL || reg == A840_RB_GC_GMEM_PROTECT) continue;
        check(pipes & 1 ? A840_PIPE_NONE : pipes & 2 ? A840_PIPE_BR : A840_PIPE_BV, MyronA840Nonctxt[i][0], MyronA840Nonctxt[i][1]);
    }
    aperture(A840_PIPE_NONE);
    m.status = gpuRd(A840_RBBM_STATUS);
    m.int0 = gpuRd(A840_RBBM_INT_0_STATUS);
    m.cp_int = gpuRd(A840_CP_INTERRUPT_STATUS_GLOBAL);
    if (grd(nullptr, MGM_WIN_CXMISC, A840_CX_MISC_SW_FUSE_FREQ_LIMIT_STATUS * 4, &m.fuse_freq)) ++m.io_errors;
    if (grd(nullptr, MGM_WIN_CXMISC, A840_CX_MISC_SW_FUSE_VALUE * 4, &m.fuse_value)) ++m.io_errors;
    if (grd(nullptr, MGM_WIN_CXMISC, A840_CX_MISC_SLICE_ENABLE_FINAL * 4, &m.slices)) ++m.io_errors;
}

// Mode 8. The command processor as a6xx_ucode_load and the rest of hw_init start it. The GPU's own SMMU context comes from
// NativeAdrenoGpuContextBringup: context bank 0 (arm-smmu-qcom gives the GPU bank 0), ASID 2, stream slots 0/1 for myron's
// gfx3d_user and gfx3d_lpac streams 0 and 1 (gfx3d_secure, stream 2, stays unmatched and faults), with its ring, memptrs,
// power-up list and scratch pages. The AQE microcode goes into the context's firmware buffer; the SQE microcode, too big
// for it on gen8, into a buffer of its own. Both drop their first dword, as adreno_fw_create_bo copies them.
constexpr unsigned kGpuBank = 0, kGpuAsid = 2;
constexpr uint64_t kSqeIova = 0x400000;          // below the GMEM range and clear of the context's buffers
constexpr size_t kSqeBytes = 0x1e000;
constexpr uint32_t kScratchMagic = 0x5e9a8400u;
// adreno_pm4.xml opcodes.
enum : uint32_t {kPm4WaitMemWrites = 0x12, kPm4ThreadControl = 0x17, kPm4MemWrite = 0x3d, kPm4EventWrite7 = 0x46,
                 kPm4MeInit = 0x48, kPm4SetSecureMode = 0x66};
NativeAdrenoMemory gSqe;
volatile uint32_t *gGpuCpu[5];                   // write-combined views of sqe(aqe here), ring, memptrs, pwrup, scratch
void gpuCtxProgress(uint32_t step) {myron_gpu_stage = 0x80000000u | step;}




// a6xx_flush: the ring words are Normal non-cacheable on both sides, so ordering them before the WPTR write is enough.

// A CACHE_CLEAN timestamp into memptrs+4 (msm_rbmemptrs.fence) after a CP_WAIT_MEM_WRITES, then the wait for it (100 us
// steps, up to 200 ms).

size_t bank0() {
    const uint32_t id1 = *reinterpret_cast<volatile uint32_t *>(gSmmu.va + 0x24);
    const size_t page = (id1 >> 31) ? 0x10000 : 0x1000, bank = page << (((id1 >> 28) & 7) + 1);
    return bank + 0x1000 <= kSmmuWindow ? bank : 0;
}
uint32_t smmuRd(size_t offset) {return gSmmu.va && offset ? *reinterpret_cast<volatile uint32_t *>(gSmmu.va + offset) : 0xdead;}


// Mode 8's first half, shared with the run mode: the GPU's SMMU context and buffers, the SQE buffer and both microcode
// images read back; true once all of it is in place.
bool cpPrepare() {
    Mode8 &m = gM8;
    if (!gM7.ran || gM7.io_errors || !gM7.checked || gM7.matched != gM7.checked || !gSmmu.va) return false;
    m.ran = 1;
    // 1. Stream slots 0 and 1 unused (SMR invalid) and faulting, as the kit requires.
    m.step = 1;
    for (unsigned i = 0; i < 2; ++i) {
        volatile uint32_t *smr = reinterpret_cast<volatile uint32_t *>(gSmmu.va + MG_SMMU_SMR(i));
        volatile uint32_t *s2cr = reinterpret_cast<volatile uint32_t *>(gSmmu.va + MG_SMMU_S2CR(i));
        m.s2cr_before[i] = *s2cr;
        if (*smr & (1u << 31)) return false;
        if (((m.s2cr_before[i] >> 16) & 3) != 2) {*s2cr = 0x20000; __asm__ volatile("dsb sy" ::: "memory"); m.s2cr_fixed |= 1u << i;}
    }
    m.step = 2;
    m.ctx_status = NativeAdrenoGpuContextBringup(reinterpret_cast<volatile uint8_t *>(gSmmu.va), kSmmuWindow, kGpuBank, kGpuAsid,
                                                 0, 0, 1, 1, gpuCtxProgress, &m.ctx);
    if (m.ctx_status) return false;
    const size_t b = bank0();
    m.actlr = smmuRd(b ? b + 0x4 : 0);
    // sheng's countermeasure (GpuPowerProbe.cpp gpuSetActlr): the bootloader leaves the bank's ACTLR at 0x3, CPRE on, and MMU-500 errata
    // 841119/826419 let that next-page prefetcher keep stale translations after a TLB invalidation. Linux clears CPRE in every bank, and
    // sheng sets the Adreno bank to 0x301 (CMTLB | PREFETCH_DEEP, CPRE off), as Linux's driver left it, before any GPU buffer is mapped,
    // then invalidates the bank's TLB (TLBIALL +0x618, TLBSYNC +0x7f0, TLBSTATUS +0x7f4). With CPRE on (myron to boot-myron-30) the GPU
    // read freed surfaces' pages after their reuse (Settings labels showing SpringBoard's) and hung in the same draw each time.
    // myron-gpu-actlr=<value> sets another value; 0 leaves the bootloader's.
    unsigned actlr = 0x301;
    PE_parse_boot_argn("myron-gpu-actlr", &actlr, sizeof actlr);
    m.actlr_set = m.actlr;
    if (b && actlr) {
        volatile uint32_t *cb = reinterpret_cast<volatile uint32_t *>(gSmmu.va + b);
        cb[0x4 / 4] = actlr;
        __asm__ volatile("dsb sy" ::: "memory");
        cb[0x618 / 4] = 0;
        cb[0x7f0 / 4] = 0;
        for (unsigned i = 0; i < 1000 && (cb[0x7f4 / 4] & 1); ++i) IODelay(1);
        if (cb[0x7f4 / 4] & 1) return false;
        m.actlr_set = cb[0x4 / 4];
        if (m.actlr_set != actlr) return false;
    }
    m.step = 3;
    m.buf_status = NativeAdrenoGpuContextBuffers(m.buf);
    if (m.buf_status) return false;
    static Window views[5];
    for (unsigned i = 0; i < 5; ++i) {
        views[i] = {m.buf[i].physical, m.buf[i].bytes, nullptr, 0};
        if (!mapOne(views[i], kIOMapWriteCombineCache)) return false;
        gGpuCpu[i] = reinterpret_cast<volatile uint32_t *>(views[i].va);
        ++m.views;
    }
    m.step = 4;
    NativeAdrenoVm *vm = NativeAdrenoGpuContextVm();
    if (!vm) return false;
    m.sqe_alloc = gSqe.allocate(kSqeBytes, m.ctx.output_bits, true, kSqeBytes);
    if (m.sqe_alloc || gSqe.spanCount() != 1) return false;
    uint64_t handle = 0;
    m.sqe_map = vm->map(&gSqe, 0, kSqeIova, 5, 0, 2, &handle);   // read + execute, as the kit maps its SQE buffer
    if (m.sqe_map) return false;
    m.sqe_phys = gSqe.spans()[0].physical;
    static Window sqe;
    sqe = {m.sqe_phys, kSqeBytes, nullptr, 0};
    if (!mapOne(sqe, kIOMapWriteCombineCache)) return false;
    // 2. The microcode without its first dword, read back in full.
    m.step = 5;
    if (myron_sqe_firmware_size < 8 || myron_sqe_firmware_size - 4 > kSqeBytes || myron_aqe_firmware_size < 8 ||
        myron_aqe_firmware_size - 4 > m.buf[0].bytes) return false;
    volatile uint8_t *sqeCpu = reinterpret_cast<volatile uint8_t *>(sqe.va), *aqeCpu = reinterpret_cast<volatile uint8_t *>(gGpuCpu[0]);
    for (uint64_t i = 4; i < myron_sqe_firmware_size; ++i) sqeCpu[i - 4] = myron_sqe_firmware[i];
    for (uint64_t i = 4; i < myron_aqe_firmware_size; ++i) aqeCpu[i - 4] = myron_aqe_firmware[i];
    __asm__ volatile("dsb sy" ::: "memory");
    for (uint64_t i = 4; i < myron_sqe_firmware_size && !m.sqe_bad; ++i) if (sqeCpu[i - 4] != myron_sqe_firmware[i]) m.sqe_bad = uint32_t(i - 3);
    for (uint64_t i = 4; i < myron_aqe_firmware_size && !m.aqe_bad; ++i) if (aqeCpu[i - 4] != myron_aqe_firmware[i]) m.aqe_bad = uint32_t(i - 3);
    if (m.sqe_bad || m.aqe_bad) return false;
    // The power-up list stays empty (all lengths 0), as Linux's is at the first CP_ME_INIT: a8xx_patch_pwrup_reglist runs
    // after it. The ring, memptrs and scratch start zeroed.
    for (unsigned i = 1; i < 5; ++i) for (size_t w = 0; w < m.buf[i].bytes / 4; ++w) gGpuCpu[i][w] = 0;
    __asm__ volatile("dsb sy" ::: "memory");
    return true;
}



// Mode 9. zap_shader_load_mdt / qcom_mdt_load as sheng's zapAndSecure makes them, into myron's gpu_microcode_region (the
// zap-shader memory-region of the kgsl node): PAS 13 init_image with the ELF header and the hash segment, mem_setup over
// the relocatable span, the segment copy, auth_and_reset; then, only if TrustZone accepted it, hw_init's CP_SET_SECURE_MODE 0
// with a fence, RB_GC_GMEM_PROTECT (after the exit, as hw_init orders it) and a second fenced CP_MEM_WRITE.
constexpr uint64_t kScmPil(uint32_t cmd) {return 0x42000000u | (0x02u << 8) | cmd;}   // SIP, QCOM_SCM_SVC_PIL
constexpr uint32_t kGpuPasId = 13;                                                    // GPU_PAS_ID
constexpr uint64_t kZapPhys = 0x9959a000, kZapBytes = 0x2000;                         // gpu_microcode_region@9959a000
NativeAdrenoMemory gZapMetadata;
uint32_t rd32le(const uint8_t *p) {return uint32_t(p[0]) | uint32_t(p[1]) << 8 | uint32_t(p[2]) << 16 | uint32_t(p[3]) << 24;}
uint16_t rd16le(const uint8_t *p) {return uint16_t(p[0] | p[1] << 8);}
int64_t scmResult(const ScmRes &r) {return r.a0 ? r.a0 : int64_t(r.a1);}

// The TrustZone half of mode 9, shared with the run mode: true once PAS 13 authenticated the zap shader.
bool zapLoad() {
    Mode9 &m = gM9;
    m.ran = 1;
    const uint8_t *fw = myron_zap_firmware;
    const uint64_t size = myron_zap_firmware_size;
    // mdt_header_valid / qcom_mdt_read_metadata: ELF32, 32-byte program headers inside the file, at least two, the first not
    // PT_LOAD, a hash segment (segment type 2 in p_flags bits 26:24).
    m.stage = 1;
    if (size < 52 || fw[0] != 0x7f || fw[1] != 'E' || fw[2] != 'L' || fw[3] != 'F' || fw[4] != 1) {m.stage = -1; return false;}
    const uint32_t phoff = rd32le(fw + 28);
    const unsigned phent = rd16le(fw + 42), phnum = rd16le(fw + 44);
    if (phent != 32 || phnum < 2 || phnum > 16 || phoff + uint64_t(phnum) * 32 > size) {m.stage = -2; return false;}
    auto ph = [&](unsigned i, unsigned field) {return rd32le(fw + phoff + i * 32 + field * 4);};   // type off va pa filesz memsz flags
    if (ph(0, 0) == 1) {m.stage = -3; return false;}
    unsigned hash = 0;
    for (unsigned i = 1; i < phnum && !hash; ++i) if (((ph(i, 6) >> 24) & 7) == 2) hash = i;
    if (!hash) {m.stage = -4; return false;}
    uint64_t lo = ~0ull, hi = 0;
    bool relocate = false;
    for (unsigned i = 0; i < phnum; ++i) {
        if (ph(i, 0) != 1 || ((ph(i, 6) >> 24) & 7) == 2 || !ph(i, 5)) continue;   // mdt_phdr_loadable
        if (ph(i, 6) & (1u << 27)) relocate = true;
        lo = lo < ph(i, 3) ? lo : ph(i, 3);
        const uint64_t end = (uint64_t(ph(i, 3)) + ph(i, 5) + 0xfff) & ~0xfffull;
        hi = hi > end ? hi : end;
    }
    if (lo >= hi || hi - lo > kZapBytes) {m.stage = -5; return false;}
    const uint64_t ehdr = ph(0, 4), hashBytes = ph(hash, 4), hashOff = ph(hash, 1);
    if (ehdr > size || hashOff + hashBytes > size || ehdr + hashBytes > 0x4000) {m.stage = -6; return false;}
    // Metadata: physically contiguous, page aligned, pushed to the point of coherency (Linux: dma_alloc_coherent).
    m.stage = 2;
    const size_t metaBytes = size_t((ehdr + hashBytes + 0xfff) & ~0xfffull);
    if (gZapMetadata.allocate(metaBytes, 40, true, metaBytes) || gZapMetadata.spanCount() != 1) {m.stage = -7; return false;}
    uint8_t *meta = static_cast<uint8_t *>(gZapMetadata.mapping());
    for (uint64_t i = 0; i < ehdr; ++i) meta[i] = fw[i];
    for (uint64_t i = 0; i < hashBytes; ++i) meta[ehdr + i] = fw[hashOff + i];
    if (gZapMetadata.publishForDevice(0, metaBytes, true)) {m.stage = -8; return false;}
    // qcom_scm_pas_init_image: ARGS(2, VAL, RW).
    m.stage = 3;
    ScmRes r = scmCall(kScmPil(0x01), 2 | (2u << 6), kGpuPasId, gZapMetadata.spans()[0].physical);
    m.init = scmResult(r);
    m.resumes[0] = r.resumes;
    if (m.init) return false;
    if (relocate) {
        // qcom_scm_pas_mem_setup: ARGS(3).
        m.stage = 4;
        r = scmCall(kScmPil(0x02), 3, kGpuPasId, kZapPhys, hi - lo);
        m.mem = scmResult(r);
        m.resumes[1] = r.resumes;
        if (m.mem) return false;
    }
    // qcom_mdt_load_no_init into the reserved region (relocatable: offsets from the lowest segment address); the CPU view is
    // gone before TrustZone takes the region.
    m.stage = 5;
    {
        Window region = {kZapPhys, kZapBytes, nullptr, 0};
        if (!mapOne(region, kIOMapWriteCombineCache)) {m.stage = -9; return false;}
        volatile uint8_t *dst = reinterpret_cast<volatile uint8_t *>(region.va);
        const uint64_t base = relocate ? lo : kZapPhys;
        bool fits = true;
        for (unsigned i = 0; i < phnum && fits; ++i) {
            if (ph(i, 0) != 1 || ((ph(i, 6) >> 24) & 7) == 2 || !ph(i, 5)) continue;
            const uint64_t to = uint64_t(ph(i, 3)) - base, file = ph(i, 4), mem = ph(i, 5), off = ph(i, 1);
            if (ph(i, 3) < base || to + mem > kZapBytes || file > mem || off + file > size) {fits = false; break;}
            for (uint64_t k = 0; k < file; ++k) dst[to + k] = fw[off + k];
            for (uint64_t k = file; k < mem; ++k) dst[to + k] = 0;
        }
        __asm__ volatile("dsb sy" ::: "memory");
        region.map->release();
        if (!fits) {m.stage = -10; return false;}
    }
    // qcom_scm_pas_auth_and_reset: ARGS(1).
    m.stage = 6;
    r = scmCall(kScmPil(0x05), 1, kGpuPasId);
    m.auth = scmResult(r);
    m.resumes[2] = r.resumes;
    if (m.auth) return false;
    return true;
}



// Modes 10 and 11, the run mode: after mode 7's registers and cpPrepare's buffers and microcode, the command processor through
// NativeAdreno's own ring, CP start, interrupt decoder and timer on the A8XX register table, the zap shader, the GPU interrupt,
// the timer and the published service with two client rounds through it, as sheng's gpuStart and publishAndWrapperTest make
// them for the A740.
struct Mode10 {
    int ran;
    unsigned step;   // 1 ring attached, 2 CP init fenced, 3 first write seen, 4 zap and secure exit, 5 interrupt, 6 timer,
                     // 7 submit attached, 8 published, 9 client rounds run, 10 both rounds read back
    IOReturn ring_attach, cp_init, irq_mask, irq_attach, timer, submit, publish;
    int init_wait, write_wait, secure_wait, nop_wait;   // NativeAdrenoRingFence
    uint32_t init_fence, init_seen, write_seen, scratch, secure_seen, irq_readback, irq_before, irq_after, irq_seen;
    uint64_t irq_router, ticks0, ticks1;
    int rounds[2], round_ok, round_steps, round_err_at;
    IOReturn round_err;
    uint32_t mem_status, opened, closed, status, int0, cp_int, fsr, gfsr;
};
Mode10 gM10;
NativeAdrenoRing gRing;
NativeAdrenoCpInit gCpInit;
NativeAdrenoTimer gTimer;
NativeAdrenoSubmit gSubmit;
unsigned gIbThread;   // myron-gpu-ib-thread: 0 per job (continuation jobs on BR), 1 BR, 3 BOTH
// The A840 as a client sees it: the KGSL chip id with its three slices (0x44050a31, as a8xx_gpu_get_slice_info makes it and Mesa
// names the Adreno 840), 18 MiB of GMEM at the UCHE GMEM window hw_init programs, the trap base, a client window above every
// kernel buffer and the GMEM window inside the 2 GiB aperture, and kaanapali's UBWC 6.0 (highest bank bit 16, swizzle levels 2
// and 3, eight-channel macrotiles).
NativeAdrenoAbiDeviceInfo gDeviceInfo = {0, 18u << 20, kGmemRangeMin, kUcheTrapBase, 0x20000000ull, 0x60000000ull,
                                               16, 6, 1, 6, NativeAdrenoDeviceClientIova, 0};

int ringWrite(void *, uint32_t reg, uint32_t value) {return gwr(nullptr, MGM_WIN_GPU, reg * 4, value);}
int ringRead(void *, uint32_t reg, uint32_t *value) {return grd(nullptr, MGM_WIN_GPU, reg * 4, value);}
int ringBarrier(void *) {__asm__ volatile("dsb sy" ::: "memory"); return 0;}
// The ring, memptrs and command buffers are Normal non-cacheable on both sides (GPU PTEs, CPU write-combined): ordering only.
int ringPublish(void *, const volatile uint32_t *, size_t) {__asm__ volatile("dsb sy" ::: "memory"); return 0;}
int ringAcquire(void *, volatile uint32_t *, size_t) {__asm__ volatile("dsb sy" ::: "memory"); return 0;}
uint64_t ringNow(void *) {uint64_t ns = 0; absolutetime_to_nanoseconds(mach_absolute_time(), &ns); return ns / 1000;}
// The current ArmCpu contract has no reviewed GPU SPI attachment. Keep the
// hardware mask clear and poll the real CP fence; no synthetic completion.
int ringIdle(void *) { IOSleep(1); return 0; }
const NativeAdrenoRingIo gRingIo{nullptr, ringWrite, ringRead, ringBarrier};
const NativeAdrenoRingCache gRingCache{nullptr, ringPublish, ringAcquire};
const NativeAdrenoRingClock gClock{nullptr, ringNow, ringIdle};
int timerRead(void *, uint32_t reg, uint32_t *value) {return grd(nullptr, MGM_WIN_GPU, reg * 4, value);}
const NativeAdrenoTimeIo gTimerIo{nullptr, timerRead};
// The GPU interrupt (level): NativeAdrenoIrq reads RBBM_INT_0_STATUS and clears it before the EOI. A source it cannot clear would
// keep the boot core in this handler, so a long run of empty reads masks the GPU's interrupts instead, as sheng's handler does.

// One plain kernel submission (the words, CP_SCRATCH_GLOBAL(2) and a CACHE_CLEAN timestamp) and the wait for its fence.
bool ringFence(const uint32_t *words, size_t count, int &result, uint32_t *seen) {
    uint32_t fence = 0;
    if (gRing.submit(words, count, &fence)) return false;
    result = gRing.wait(fence, &gClock, 200000, seen);
    return result == NativeAdrenoRingFenceComplete;
}
// One external-method call through the published service's user client, as a user-space caller's arrives.
IOReturn clientCall(IOUserClient *uc, uint32_t method, const void *in, void *out) {
    IOExternalMethodArguments a{};
    a.version = kIOExternalMethodArgumentsCurrentVersion;
    a.selector = method;
    const size_t is = NativeAdrenoUserClient::inputSize(method), os = NativeAdrenoUserClient::outputSize(method);
    a.structureInput = is ? in : nullptr;
    a.structureInputSize = uint32_t(is);
    a.structureOutput = os ? out : nullptr;
    a.structureOutputSize = uint32_t(os);
    return uc->externalMethod(method, &a, nullptr, nullptr, nullptr);
}
// Sheng's wrapperRound: the path a client takes, minus the Mach trap. newUserClient (a second one is refused while it is open),
// the device info, two buffer objects mapped at fixed GPU addresses and through clientMemoryForType into this task, an
// indirect buffer of three CP_MEM_WRITEs submitted (NativeAdrenoSubmit's framed submission on the A8XX ring) and waited for,
// the CPU's read-back, the timestamp, then clientClose (drain, unmap, free). Returns the matching dwords (of 4) or -1.
// The open type is the Adreno Metal plugin's, the only one NativeAdrenoPublish.cpp serves since cedcaa2 (it refuses every other
// with kIOReturnUnsupported; boot-myron-22's rounds opened with sheng's type 0 and were refused). The kernel task has its own single
// client slot, so a second open is still refused while one is live.
constexpr UInt32 kAdrenoPluginOpenType = 0x4147;
int clientRound(IOService *service) {
    Mode10 &m = gM10;
    auto step = [&](IOReturn s) {
        const int index = m.round_steps++;
        if (!s) ++m.round_ok;
        else if (!m.round_err) {m.round_err = s; m.round_err_at = index;}
        return !s;
    };
    IOUserClient *uc = nullptr;
    if (!step(service->newUserClient(kernel_task, nullptr, kAdrenoPluginOpenType, nullptr, &uc)) || !uc) return -1;
    IOUserClient *second = nullptr;
    step(service->newUserClient(kernel_task, nullptr, kAdrenoPluginOpenType, nullptr, &second) == kIOReturnBusy ? 0 : kIOReturnError);
    if (second) second->release();
    NativeAdrenoAbiParams params{};
    step(clientCall(uc, NativeAdrenoMethodQuery, nullptr, &params));
    NativeAdrenoAbiDeviceInfo info{};
    step(clientCall(uc, NativeAdrenoMethodGetDeviceInfo, nullptr, &info));
    step(info.chip_id == gDeviceInfo.chip_id && info.gmem_bytes == gDeviceInfo.gmem_bytes ? 0 : kIOReturnError);
    NativeAdrenoAbiBoAlloc alloc{4096, 12, 0};
    NativeAdrenoAbiBoAllocReply ib{}, target{};
    int matched = -1;
    IOMemoryDescriptor *desc[2] = {};
    IOMemoryMap *maps[2] = {};
    if (step(clientCall(uc, NativeAdrenoMethodBoAlloc, &alloc, &ib)) && step(clientCall(uc, NativeAdrenoMethodBoAlloc, &alloc, &target))) {
        const uint64_t ibIova = 0x20004000, targetIova = 0x20005000;
        NativeAdrenoAbiBoMap mapIb{ib.handle, ibIova, 1, 0, 2, 0}, mapTarget{target.handle, targetIova, 3, 0, 2, 0};
        NativeAdrenoAbiBoMapReply mr{};
        NativeAdrenoAbiBoCpuMap cpuIb{ib.handle}, cpuTarget{target.handle};
        NativeAdrenoAbiBoCpuMapReply crIb{}, crTarget{};
        if (step(clientCall(uc, NativeAdrenoMethodBoMap, &mapIb, &mr)) && step(clientCall(uc, NativeAdrenoMethodBoMap, &mapTarget, &mr)) &&
            step(clientCall(uc, NativeAdrenoMethodBoCpuMap, &cpuIb, &crIb)) &&
            step(clientCall(uc, NativeAdrenoMethodBoCpuMap, &cpuTarget, &crTarget))) {
            IOOptionBits options[2] = {};
            const uint32_t tokens[2] = {crIb.token, crTarget.token};
            bool mapped = true;
            for (int i = 0; i < 2; ++i) {
                const IOReturn s = uc->clientMemoryForType(tokens[i], &options[i], &desc[i]);
                if (!m.mem_status) m.mem_status = uint32_t(s);
                if (s || !desc[i]) {mapped = false; continue;}
                maps[i] = desc[i]->createMappingInTask(kernel_task, 0, options[i]);
                if (!maps[i]) {mapped = false; if (!m.mem_status) m.mem_status = 0xbad;}
            }
            step(mapped ? 0 : kIOReturnNoMemory);
            if (mapped) {
                volatile uint32_t *iw = reinterpret_cast<volatile uint32_t *>(maps[0]->getVirtualAddress());
                volatile uint32_t *tw = reinterpret_cast<volatile uint32_t *>(maps[1]->getVirtualAddress());
                for (unsigned i = 0; i < 1024; ++i) tw[i] = 0xdeadbeef;
                const uint32_t values[3] = {0x0a840c0d, 0xfeed0840, 0x600d0000u | uint32_t(m.round_steps)};
                uint32_t words[12];
                bool built = true;
                for (unsigned i = 0; i < 3; ++i) {
                    built = built && AdrenoPM4Type7(kPm4MemWrite, 3, &words[i * 4]) == AdrenoPM4Success;
                    words[i * 4 + 1] = uint32_t(targetIova + i * 4); words[i * 4 + 2] = uint32_t(targetIova >> 32);
                    words[i * 4 + 3] = values[i];
                }
                for (unsigned i = 0; i < 12; ++i) iw[i] = words[i];
                __asm__ volatile("dsb sy" ::: "memory");
                NativeAdrenoAbiSubmit submit{};
                submit.buffer_count = 1;
                submit.buffers[0] = {ib.handle, ibIova, sizeof words};
                NativeAdrenoAbiSubmitReply sr{};
                if (step(built ? 0 : kIOReturnInternalError) && step(clientCall(uc, NativeAdrenoMethodSubmit, &submit, &sr))) {
                    NativeAdrenoAbiWaitFence wait{sr.fence, 200000000ull};
                    if (step(clientCall(uc, NativeAdrenoMethodWaitFence, &wait, nullptr))) {
                        __asm__ volatile("dsb sy" ::: "memory");
                        matched = (tw[0] == values[0]) + (tw[1] == values[1]) + (tw[2] == values[2]) + (tw[3] == 0xdeadbeef);
                    }
                }
                NativeAdrenoAbiTimestamp ts{};
                step(clientCall(uc, NativeAdrenoMethodGetTimestamp, nullptr, &ts));
            }
        }
    }
    for (auto *map : maps) if (map) map->release();
    for (auto *d : desc) if (d) d->release();
    step(uc->clientClose());
    uc->release();
    return matched;
}

void runSteps() {
    Mode10 &m = gM10;
    // Read the active slices before publishing a Mesa identity. The current
    // GMEM/non-context setup is qualified only for all three A840 slices.
    const uint32_t chip = mg_a840_chip_id(gM7.slices, !gM7.ran || gM7.io_errors);
    if (chip != 0x44050a31u) return;
    gDeviceInfo.chip_id = chip;
    unsigned pool = MYRON_GPU_POOL_MIB;
    PE_parse_boot_argn("myron-gpu-pool", &pool, sizeof pool);
    native_adreno_pool_mib = myron_gpu_pool_mib(pool);
    if (!cpPrepare()) return;
    m.ran = 1;
    const Mode8 &p = gM8;
    // adreno_hw_init's ring through NativeAdrenoRing on the A8XX table (base, control, rptr shadow at memptrs+0, WPTR and the fence
    // scratch), then what the ring object does not program: the microcode bases and the BV rptr shadow at memptrs+8.
    if (gRing.useChip(&NativeAdrenoChipA8xx)) return;
    // The user words' thread, myron-gpu-ib-thread: 0 (default) per job, through NativeAdrenoSubmit::setContinuationThread below; 1 BR
    // for every job; 3 BOTH for every job (a7xx_submit). boot-myron-37's debug page showed a job that began inside a Turnip command buffer
    // (row-by-row 2D blits of the scanout copy) run its blits on BV under BOTH while BR waited for idle; boot-myron-38, with every job
    // on BR, stopped before the Apple logo because BV never saw Turnip's command-buffer prologue.
    PE_parse_boot_argn("myron-gpu-ib-thread", &gIbThread, sizeof gIbThread);
    if (gIbThread != 1 && gIbThread != 3) gIbThread = 0;
    if (gRing.setUserThread(gIbThread == 1 ? 1 : 3)) return;
    m.ring_attach = gRing.attach(&gRingIo, &gRingCache, const_cast<uint32_t *>(gGpuCpu[1]), p.buf[1].bytes, p.buf[1].iova,
                                 const_cast<uint32_t *>(gGpuCpu[2]), p.buf[2].bytes, p.buf[2].iova);
    if (m.ring_attach) return;
    m.step = 1;
    gpuWr64(A840_CP_SQE_INSTR_BASE, kSqeIova);
    gpuWr64(A840_CP_AQE_INSTR_BASE_0, p.buf[0].iova);
    gpuWr64(A840_CP_RB_RPTR_ADDR_BV, p.buf[2].iova + 8);
    gpuWr(A840_CP_SQE_CNTL, 1);
    // a8xx_cp_init through NativeAdrenoCpInit, which reads back the SQE base written above, before CP_SQE_CNTL.
    const NativeAdrenoCpInitConfig config{kSqeIova, p.buf[3].iova, 1};
    if (gCpInit.useChip(&NativeAdrenoChipA8xx)) return;
    m.cp_init = gCpInit.run(&gRingIo, &gRing, &config, &m.init_fence);
    if (m.cp_init) return;
    m.init_wait = gRing.wait(m.init_fence, &gClock, 200000, &m.init_seen);
    if (m.init_wait) return;
    m.step = 2;
    // The first command after it: a fenced CP_MEM_WRITE into the scratch page.
    volatile uint32_t *scratch = gGpuCpu[4];
    scratch[0] = 0;
    __asm__ volatile("dsb sy" ::: "memory");
    uint32_t write[4] = {};
    if (AdrenoPM4Type7(kPm4MemWrite, 3, &write[0]) != AdrenoPM4Success) return;
    write[1] = uint32_t(p.buf[4].iova); write[2] = uint32_t(p.buf[4].iova >> 32); write[3] = kScratchMagic;
    if (!ringFence(write, 4, m.write_wait, &m.write_seen)) return;
    m.scratch = scratch[0];
    if (m.scratch != kScratchMagic) return;
    m.step = 3;
    // The zap shader through TrustZone, then CP_SET_SECURE_MODE 0 and GMEM protection, in hw_init's order.
    if (!zapLoad()) return;
    uint32_t secure[2] = {};
    if (AdrenoPM4Type7(kPm4SetSecureMode, 1, &secure[0]) != AdrenoPM4Success) return;
    if (!ringFence(secure, 2, m.secure_wait, &m.secure_seen)) return;
    pipeWr(A840_PIPE_BR, A840_RB_GC_GMEM_PROTECT, A840_GMEM_PROTECT);
    aperture(A840_PIPE_NONE);
    m.step = 4;
    // Poll actual fenced work until this board's GIC hookup is qualified.
    gpuWr(A840_RBBM_INT_0_MASK, 0);
    if (gpuRd(A840_RBBM_INT_0_MASK) != 0 || gM7.io_errors) return;
    uint32_t nop = 0;
    if (AdrenoPM4Type7(0x10, 0, &nop) != AdrenoPM4Success ||
        !ringFence(&nop, 1, m.nop_wait, nullptr)) return;
    m.step = 5;
    // The always-on counter (19.2 MHz) through the A8XX table, twice, 10 ms apart.
    if (gTimer.useChip(&NativeAdrenoChipA8xx)) return;
    m.timer = gTimer.attach(&gTimerIo, NativeAdrenoTimeCp);
    if (m.timer) return;
    if (gTimer.read(&m.ticks0)) return;
    IOSleep(10);
    if (gTimer.read(&m.ticks1) || m.ticks1 <= m.ticks0) return;
    m.step = 6;
    NativeAdrenoVm *vm = NativeAdrenoGpuContextVm();
    // Retain explicit cache maintenance until bidirectional coherence is
    // proved on this kernel. CPU imports are never assumed coherent.
    native_adreno_io_coherent = 0;
    native_adreno_flush_imports = 1;
    m.submit = vm ? gSubmit.attach(vm, &gRing) : kIOReturnNotReady;
    if (m.submit) return;
    gSubmit.setContinuationThread(gIbThread == 0);
    m.step = 7;
    m.publish = native_adreno_publish(vm, &gSubmit, &gRing, &gClock, &gTimer, &gDeviceInfo, 31, 40);
    IOService *service = m.publish ? nullptr : native_adreno_published_service();
    if (!service) return;
    m.step = 8;
    m.rounds[0] = clientRound(service);
    m.rounds[1] = clientRound(service);   // the client slot must recycle; the close unmapped the round's addresses
    m.opened = native_adreno_publish_stats(&m.closed);
    m.step = 9;
    if (m.rounds[0] == 4 && m.rounds[1] == 4 && !m.round_err && m.opened == 2 && m.closed == 2) m.step = 10;
}


} // namespace

// Called after the generated late initializer registration. There is one
// startup per boot; failed hardware resources remain quarantined for reset.
extern "C" size_t myron_gpu_snapshot(char *out, size_t cap) {
    if(!out || !cap)return 0;
    // Publish the result array only after the worker stops changing it.
    const uint32_t complete=__atomic_load_n(&myron_gpu_complete,__ATOMIC_ACQUIRE);
    int n=snprintf(out,cap,"[myron gpu] complete=%u mmio=%08x ready=%u cc=%u cx=%u gmu=%u hfi=%u cp=%u zap=%u submit=%u rounds=%u/%u error=%08x pool=%u metal=0\n",
        complete,__atomic_load_n(&myron_gpu_stage,__ATOMIC_RELAXED),
        __atomic_load_n(&myron_gpu_ready,__ATOMIC_ACQUIRE),
        complete?gpuResult[0]:0,complete?gpuResult[1]:0,complete?gpuResult[2]:0,
        complete?gpuResult[3]:0,complete?gpuResult[4]:0,complete?gpuResult[5]:0,
        complete?gpuResult[6]:0,complete?gpuResult[7]:0,complete?gpuResult[8]:0,
        complete?gpuResult[9]:0,complete?gpuResult[10]:0);
    size_t used=n<0?0:((size_t)n<cap?(size_t)n:cap-1);
    if(complete && used<cap-1) {
        n=snprintf(out+used,cap-used,
            "gpu_init ran=%u io_errors=%u checked=%u matched=%u slices=%08x chip=%08x smmu=%u\n"
            "gpu_bad1 reg=%08x got=%08x want=%08x bad2 reg=%08x got=%08x want=%08x\n",
            unsigned(gM7.ran),gM7.io_errors,gM7.checked,gM7.matched,gM7.slices,
            mg_a840_chip_id(gM7.slices,!gM7.ran || gM7.io_errors),unsigned(gSmmu.va!=0),
            gM7.bad_reg,gM7.bad_got,gM7.bad_want,gM7.bad2_reg,gM7.bad2_got,gM7.bad2_want);
        if(n>0)used+=(size_t)n<cap-used?(size_t)n:cap-used-1;
    }
    return used;
}
extern "C" void myron_gpu_run(void *, wait_result_t)
{
    const unsigned have = mapWindows(gWindows, MG_WINDOWS);
    mg_io io = {nullptr, rd, wr, delayUs};
    static mg_result result;
    mg_run(&io, 11, have, &result);
    if (result.cc == MG_DONE && mg_gdsc_on(result.cx_hwctrl) && !result.io_error) {
        mode4(io, result, have);
        mode5(result);
        mode6();
        mode7();
        runSteps();
    }
    const bool passed = myron_gpu_submission_ready(gM10.step, gM10.rounds[0], gM10.rounds[1],
        gM10.round_err, gM10.opened, gM10.closed);
    gpuResult[0]=result.cc;gpuResult[1]=result.cx_hwctrl;gpuResult[2]=gM5.gmu.phase;
    gpuResult[3]=gM6.step;gpuResult[4]=gM8.step;gpuResult[5]=gM9.stage;
    gpuResult[6]=gM10.step;gpuResult[7]=gM10.rounds[0];gpuResult[8]=gM10.rounds[1];
    gpuResult[9]=gM10.round_err;gpuResult[10]=native_adreno_pool_status;
    if(passed && myron_display_register_gpu_fences(myron_gpu_query_fences))
        __atomic_store_n(&myron_gpu_ready,1,__ATOMIC_RELEASE);
    __atomic_store_n(&myron_gpu_complete,1,__ATOMIC_RELEASE);
    IOLog("myron-gpu: native A840 stage=%u readback=%d/%d qualified=%u; Metal not published\n",
          gM10.step, gM10.rounds[0], gM10.rounds[1], unsigned(passed));
    thread_terminate(current_thread());
}
