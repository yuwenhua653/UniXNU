/* SPDX-License-Identifier: GPL-2.0-only */
#include "MyronSE19.h"

static void delay_us(void *context, unsigned delay)
{
    struct geni_spi *se = context;
    se->se.delay_us(se->se.ctx, delay);
}

static int transfer(void *context, const uint8_t *tx, uint8_t *rx, size_t bytes)
{
    struct geni_spi *se = context;
    if (!tx || !rx || !bytes || bytes > MYRON_SPI_BYTES)
        return GENI_ERR_PARAM;
    /* One command drives CS0 across the header, dummy bytes, data and CRC. */
    return geni_spi_transfer(se, tx, rx, bytes, 0);
}

int myron_se19_start(struct myron_touch *sensor, struct geni_spi *se,
                     unsigned source_hz, unsigned selector)
{
    if (!sensor || sensor->ready || !se || !se->se.rd || !se->se.wr ||
        !se->se.delay_us || !se->wrapper.rd || !source_hz || selector > 7)
        return GENI_ERR_PARAM;
    int rc = geni_spi_read_info(se);
    if (rc) return rc;
    if (se->info.protocol != GENI_PROTO_SPI) return GENI_ERR_PROTO;
    if (se->info.geni_status & GENI_STATUS_M_ACTIVE) return GENI_ERR_IO;
    if (se->info.fifo_disabled && !se->use_dma) return GENI_ERR_NOTSUP;
    if (se->use_dma && (se->dma.size < MYRON_SPI_BYTES ||
                        !se->dma.tx_virt || !se->dma.rx_virt ||
                        !se->dma.tx_phys || !se->dma.rx_phys))
        return GENI_ERR_PARAM;
    se->allow_fifo_disabled = 0;
    se->poll_only = 2;
    rc = geni_spi_init(se);
    if (!rc) rc = geni_spi_set_clock(se, 9600000, source_hz, selector);
    if (!rc) rc = geni_spi_setup(se, 0, 0);
    if (rc) return rc;
    sensor->bus = (struct myron_touch_bus){se, transfer, delay_us};
    return myron_touch_identify_and_start(sensor);
}
