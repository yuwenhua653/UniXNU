# FT3683 on QUP4 SE0

The Android myron touchscreen binds to spi19.0 under spi@1a80000 and the QUP wrapper at 0x1ac0000. This board adapter connects the FT3683 protocol implementation to QcomGeniSpi. It is staged separately from MyronDigitizer until the platform supplies the touch engine's clock, pin configuration and DMA mapping.

Build the register-model regression from the repository root with a checkout of UniXNU/QcomGeniSpi at eac47baefe6a5d2368a70351e6ad1b6361bedbe2.

```sh
cc -std=c11 -Wall -Wextra -Werror -I"$QCOM_GENI_SPI" \
   myron-touch/se19/MyronSE19.c myron-touch/se19/test_se19.c \
   myron-touch/MyronFT3683.c "$QCOM_GENI_SPI/GeniSpi.c" -o /tmp/test-myron-se19
/tmp/test-myron-se19
```

The test assigns distinct synthetic TX and RX device addresses and exercises chip identification, TIC mode readback, CRC rejection and press/release reports through SE DMA. The platform caller must prepare device-owned DMA buffers and maintain their coherency for the full polling lifetime.
