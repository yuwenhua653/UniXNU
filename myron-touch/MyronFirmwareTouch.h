/* SPDX-License-Identifier: GPL-2.0-only */
/* Graphical myron firmware supplies the touch I/O rail before starting XNU.
 * The minimal board maps both AOP RAM and the APSS RSC as device memory. */
#ifndef MYRON_FIRMWARE_TOUCH_H
#define MYRON_FIRMWARE_TOUCH_H
#define MYRON_TOUCH_EDK2
#include "MyronTouchPower.h"

STATIC uint32_t MyronRscRead (void *Context, unsigned Offset)
{
  return ((volatile uint32_t *)Context)[Offset / 4];
}
STATIC void MyronRscWrite (void *Context, unsigned Offset, uint32_t Value)
{
  ((volatile uint32_t *)Context)[Offset / 4] = Value;
  __asm__ volatile ("dsb sy" ::: "memory");
}
STATIC void MyronRscDelay (void *Context, unsigned Us)
{
  (void)Context;
  gBS->Stall (Us);
}
STATIC int MyronPrimeTouchPower (VOID)
{
  const volatile uint32_t *Db = (const volatile uint32_t *)(UINTN)MYRON_CMD_DB;
  struct myron_rsc_io Io = {(void *)(UINTN)MYRON_APPS_DRV2, MyronRscRead, MyronRscWrite, MyronRscDelay};
  uint32_t Address = myron_l4i_address (Db, MYRON_CMD_DB_BYTES);
  int Result = MYRON_POWER_BUSY;

  for (unsigned Attempt = 0; Attempt < 5 && Result == MYRON_POWER_BUSY; ++Attempt) {
    if (Attempt) gBS->Stall (2000);
    Result = myron_vote_l4i (&Io, Address);
  }
  return Result;
}
#endif
