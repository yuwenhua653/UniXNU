"""Bind a committed expanded overlay to RamBlock and the Data mount gate."""
from pathlib import Path
import shutil


def once(source, old, new):
    if source.count(old) != 1:
        raise ValueError('Data capacity boundary changed: ' + old[:80])
    return source.replace(old, new)


def prepare_ram_block(source):
    # The board binds these callbacks strongly in the same translation unit.
    source = once(source,
                  'if (mode && (sparse.pages || isBig) && &myron_data_store_open && &myron_data_store_read && &myron_data_store_write &&\n'
                  '        &myron_data_store_sync && &myron_data_store_gpt_check)',
                  'if (mode && (sparse.pages || isBig))')
    source = once(source, '#include "SparseDisk.h"',
                  '#include "SparseDisk.h"\n#include "../MyronDataCapacity.h"')
    # Hashing must finish before changing the logical range. The hash remains
    # that of the original 1 GiB seed, which identifies all existing overlays.
    source = once(source, '  memcpy(native_ram_block_seed_sha256,seedHash,32);', '''  uint64_t selectedBytes=0;
  auto probe=static_cast<unsigned char *>(IOMallocZero(8192));
  if(!probe)return false;
  bool selected=myronDataProbeCapacity(seedHash,logical,probe,&selectedBytes);
  IOFree(probe,8192);
  if(!selected)return false;
  if(selectedBytes!=logical){
    struct GrowAlloc {
      void *zero(uint64_t n){return IOMallocZero(n);}
      void release(void *p,uint64_t n){IOFree(p,n);}
    } alloc;
    if(isBig || !myronDataExpandSeed(sparse,selectedBytes,alloc))return false;
    logical=selectedBytes;capacity=logical/512;
  }
  if(selectedBytes==MyronDataGrownBytes &&
     !setProperty("myron-data-grown-bytes",selectedBytes,64))return false;
  memcpy(native_ram_block_seed_sha256,seedHash,32);''')
    # APFS probes as soon as registerService publishes the provider. Attaching
    # the overlay in the later UUID resolver lets that probe cache seed-only
    # container metadata, which can disagree with a resized persisted volume.
    source = once(source, '  online = true;\n  native_ram_block_ready = 1;', '''  myronDataBootStage=1;
  IOLog("NativeRamBlock: opening persistent Data before media publication\\n");
  attachStore();
  if(!storeAttached || !direct || directFailed || !overlay.active ||
     myronDataFailed || myron_data_store_gpt_check()) {
    myronDataBootStage=3;
    IOLog("NativeRamBlock: Data publication refused, persist=%u header=%u\\n",
          (unsigned)native_data_persist_state,(unsigned)native_data_persist_header);
    return false;
  }
  myronDataBootStage=2;
  IOLog("NativeRamBlock: persistent Data ready, bytes=%llu\\n",(unsigned long long)logical);
  online = true;
  native_ram_block_ready = 1;''')
    return source


def apply(root, replace):
    here=Path(__file__).resolve().parent
    d=root/'device/myron27'; u=root/'device/sm8850/drivers/NativeUfs'
    for name in ('MyronDataGrowth.h','MyronDataCapacity.h','MyronDataMigration.h'):
        shutil.copyfile(here/name,u/name)
    shutil.copyfile(here/'data_capacity.py',d/'data_capacity.py')
    replace(u/'MyronBootLog.h','extern "C" size_t myron_staged_apps_snapshot(char *,size_t);',
            'extern "C" size_t myron_staged_apps_snapshot(char *,size_t);\n'
            'extern "C" size_t myron_data_growth_snapshot(char *,size_t);')
    replace(u/'MyronBootLog.h','  const size_t appsRemaining=',
            '  const size_t dataRemaining=MyLogSlotBlocks*MyLogBlock-(size_t)prefix;\n'
            '  prefix+=(int)myron_data_growth_snapshot((char *)slot+prefix,dataRemaining<256?dataRemaining:256);\n'
            '  const size_t appsRemaining=')
    replace(u/'MyronBootLog.h','  // Keep display status even when the general evidence fills the slot.',
            '  // Passive cached UFS diagnostics; no new transport access.\n'
            '  native_ufs_progress_text((char *)slot+prefix,2500);\n'
            '  prefix+=(int)strlen((char *)slot+prefix);\n'
            '  // Keep display status even when the general evidence fills the slot.')
    replace(u/'MyronBootLog.h','  IOSleep(2000);',
            '  IOSleep(h.rounds<20 ? 500 : 2000);')
    replace(d/'ram_data.py', '    return source',
            '    from data_capacity import prepare_ram_block\n    return prepare_ram_block(source)')
    replace(d/'ram_data.py', 'max_logical_bytes=0x80000000,',
            'max_logical_bytes=0x400000000, original_seed_bytes=0x40000000,')
    replace(d/'build_ufs_dormant.py', "'_myron_data_store_sync')",
            "'_myron_data_store_sync','_myron_data_capacity_valid')")
    p=d/'root_runtime.py'
    # The post-mount dyld gate must accept the same committed capacity as the
    # Data mount gate. The immutable seed's size/hash are still unchanged.
    replace(p,
            '        bytes != MYRON_DATA_SEED_BYTES || memcmp(digest, myron_data_expected_sha256, 32)) goto done;',
            '        (bytes != MYRON_DATA_SEED_BYTES && !(MYRON_DATA_SEED_BYTES == UINT64_C(1073741824) &&\n'
            '          myron_data_capacity_valid(bytes))) || memcmp(digest, myron_data_expected_sha256, 32)) goto done;')
    replace(p, "'_myron_start_data', '_myron_data_start_state', '_myron_data_start_status',",
            "'_myron_start_data', '_myron_data_start_state', '_myron_data_start_status',\n"
            "                '_myron_data_capacity_valid',")
    replace(p, "'extern volatile unsigned myron_data_start_state;\\n'",
            "'extern volatile unsigned myron_data_start_state;\\n'\n"
            "                'extern int myron_data_capacity_valid(uint64_t);\\n'")
    replace(p, "'if (size != MYRON_DATA_SEED_BYTES || device == NODEV ||\\n'",
            "'if ((size != MYRON_DATA_SEED_BYTES && !(MYRON_DATA_SEED_BYTES == UINT64_C(1073741824) &&\\n'\n"
            "                '\\t    myron_data_capacity_valid(size))) || device == NODEV ||\\n'")
    replace(p, "{'_native_ram_block_volume_seed', '_myron_data_start_state',",
            "{'_native_ram_block_volume_seed', '_myron_data_start_state', '_myron_data_capacity_valid',")
    replace(d/'tests/test_ram_data.py', "self.assertEqual(report['max_logical_bytes'], 1 << 31)",
            "self.assertEqual(report['max_logical_bytes'], 1 << 34)\n"
            "            self.assertEqual(report['original_seed_bytes'], 1 << 30)")
    # Run the existing real generated mount function with expanded capacity as
    # well as every existing root/cache/seed failure. No mount APIs are changed.
    p=d/'tests/test_root_runtime.py'; text=p.read_text()
    begin=text.index('    def test_data_mount_production_failure_paths(')
    end=text.index('\n    def ',begin+1); block=text[begin:end]
    block=once(block,"logical_bytes=16384, logical_sha256='42'*32)",
               "logical_bytes=1073741824, logical_sha256='42'*32)")
    block=once(block,'*size=fault==16?8192:16384;',
               '*size=fault==16?8192:fault==44?(UINT64_C(32)<<30):fault>=41?(UINT64_C(16)<<30):(UINT64_C(1)<<30);')
    block=once(block,'memset(digest,fault==17?0x41:0x42,32);',
               'memset(digest,(fault==17 || fault==43)?0x41:0x42,32);')
    block=once(block,'int copyout(const void *from,user_addr_t to,size_t n){',
               'int myron_data_capacity_valid(uint64_t bytes){return fault!=42 && bytes==(UINT64_C(16)<<30);}\n'
               'int copyout(const void *from,user_addr_t to,size_t n){')
    block=once(block,'34,35,36,40};','34,35,36,40,41,42,43,44};')
    block=once(block,'(fault==0 || fault==40)', '(fault==0 || fault==40 || fault==41)')
    block=once(block,'if((fault>=1&&fault<=19)||fault==30||fault==31)',
               'if((fault>=1&&fault<=19)||fault==30||fault==31||fault>=42)')
    p.write_text(text[:begin]+block+text[end:])
    # Keep the original small synthetic-seed test compiling under strict C11;
    # the separate full startup test exercises authorized 1/16 GiB capacities.
    text=p.read_text()
    begin=text.index('    def test_dyld_startup_production_gate_and_failures(')
    end=text.index('\n    def ',begin+1);block=text[begin:end]
    block=once(block,'int native_verified_block_root_authorized(dev_t device){',
               'int myron_data_capacity_valid(uint64_t bytes){(void)bytes;return 0;}\n'
               'int native_verified_block_root_authorized(dev_t device){')
    p.write_text(text[:begin]+block+text[end:])
