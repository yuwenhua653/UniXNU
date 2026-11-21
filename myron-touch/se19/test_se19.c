/* SPDX-License-Identifier: GPL-2.0-only */
#include "MyronSE19.h"
#include "../fts_myron_frame.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

struct model {
    uint32_t regs[0x1000 / 4];
    uint8_t tx[128], rx[128], mode;
    unsigned commands, tic_writes, reports;
    int bad_crc, up;
};
static uint32_t rd(void *p, uint32_t reg)
{
    struct model *m = p;
    return m->regs[reg/4];
}
static uint32_t wrapper(void *p, uint32_t reg)
{
    (void)p;
    assert(reg == QUPV3_HW_VER_REG);
    return 0x300a0000;
}
static void delay(void *p, unsigned us) { (void)p; assert(us); }
static void wr(void *p, uint32_t reg, uint32_t value)
{
    struct model *m = p;
    m->regs[reg/4] = value;
    if (reg == SE_DMA_TX_IRQ_CLR) m->regs[SE_DMA_TX_IRQ_STAT/4] &= ~value;
    if (reg == SE_DMA_RX_IRQ_CLR) m->regs[SE_DMA_RX_IRQ_STAT/4] &= ~value;
    if (reg == SE_GENI_M_IRQ_CLEAR) m->regs[SE_GENI_M_IRQ_STATUS/4] &= ~value;
    if (reg != SE_DMA_TX_LEN) return;
    assert(rd(m, SE_GENI_M_CMD0) == (GENI_M_CMD_TX_RX << GENI_M_OPCODE_SHIFT));
    assert(rd(m, SE_DMA_TX_PTR_L) == 0x4000 && rd(m, SE_DMA_RX_PTR_L) == 0x5000);
    assert(rd(m, SE_DMA_RX_LEN) == value && rd(m, SE_SPI_TX_TRANS_LEN) == value);
    assert(rd(m, SE_SPI_RX_TRANS_LEN) == value && value <= MYRON_SPI_BYTES);
    unsigned data = (m->tx[2] << 8) | m->tx[3];
    assert(value == 7 + data + (m->tx[1] ? 2 : 0));
    m->commands++;
    memset(m->rx, 0, value);
    if (!m->tx[1]) {
        assert(m->tx[0] == 0x9e && data == 1);
        m->mode = m->tx[7];
        m->tic_writes++;
    } else {
        assert(m->tx[1] == 0xa0);
        uint8_t *body = m->rx + 7;
        switch (m->tx[0]) {
        case 0xa3: body[0] = 0x36; break;
        case 0x9f: body[0] = 0x83; break;
        case 0x9e: body[0] = m->mode; break;
        case 1:
            assert(data == MYRON_FRAME_BYTES);
            body[1] = 0x21;
            body[4] = m->up ? 0x40 : 0x00;
            body[5] = 10;
            body[6] = 0x20;
            body[7] = 20;
            break;
        default: assert(0);
        }
        uint16_t crc = fts_myron_crc(body, data);
        body[data] = (uint8_t)(crc ^ m->bad_crc);
        body[data+1] = (uint8_t)(crc >> 8);
    }
    m->regs[SE_DMA_TX_IRQ_STAT/4] = GENI_DMA_DONE;
    m->regs[SE_DMA_RX_IRQ_STAT/4] = GENI_DMA_DONE;
}
static int report(void *p, const uint8_t *bytes, size_t len)
{
    struct model *m = p;
    assert(len == MYRON_REPORT_BYTES && bytes[0] == 3 && bytes[2] == 2);
    assert(bytes[len-1] == 1 && bytes[1] == (m->up ? 2 : 3));
    m->reports++;
    return 0;
}
int main(void)
{
    struct model m = {.mode = 0xff};
    struct myron_touch t = {0};
    struct geni_spi se = {.se = {&m, rd, wr, delay}, .wrapper = {&m, wrapper, 0, 0},
                          .dma = {.tx_virt=m.tx, .rx_virt=m.rx, .size=sizeof m.tx,
                                  .tx_phys=0x4000, .rx_phys=0x5000}, .poll_limit=100};
    m.regs[GENI_FW_REVISION_RO/4] = GENI_PROTO_SPI << GENI_FW_PROTO_SHIFT;
    m.regs[GENI_IF_DISABLE_RO/4] = GENI_FIFO_IF_DISABLE;
    m.regs[SE_HW_PARAM_0/4] = (32u << 24) | (16u << 16);
    assert(myron_se19_start(&t,&se,19200000,0) == GENI_ERR_NOTSUP && !m.commands);
    se.use_dma = 1;
    m.bad_crc = 1;
    assert(myron_se19_start(&t,&se,19200000,0) == -EBADMSG && !t.ready && !m.tic_writes);
    m.bad_crc = 0;
    assert(!myron_se19_start(&t,&se,19200000,0) && t.ready && t.chip_id == 0x3683 && m.tic_writes == 1);
    assert(rd(&m, SE_GENI_CLK_SEL) == 0 && rd(&m, GENI_SER_M_CLK_CFG) == 0x21);
    assert(!myron_touch_read_contacts(&t, report, &m) && t.active == 4);
    m.up = 1;
    assert(!myron_touch_read_contacts(&t, report, &m) && !t.active && m.reports == 2);
    puts("PASS SE19 mapped DMA, FT3683 identification, TIC, CRC rejection, touch and release");
}
