/* Execute the exact snapshot BDS source with mocked UEFI calls. No device I/O. */
#include <assert.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
#include <setjmp.h>
#include <wchar.h>
#define STATIC static
#define CONST const
#define VOID void
#define EFIAPI
#define TRUE 1
#define FALSE 0
#define MYRON_MINIMAL 1
#define DEBUG(x) ((void)0)
#define EFI_ERROR(x) ((x) != 0)
typedef uint8_t UINT8; typedef uint16_t UINT16; typedef uint32_t UINT32;
typedef size_t UINTN; typedef int BOOLEAN; typedef int EFI_STATUS;
typedef int EFI_GUID; typedef int EFI_DEVICE_PATH_PROTOCOL;
typedef int MYRON_BOOT_ENTRY; typedef int EFI_BOOT_MANAGER_LOAD_OPTION;
#define GET_GUID_HOB_DATA_SIZE(x) sizeof(MYRON_BOOT_ENTRY)
#define GET_GUID_HOB_DATA(x) (x)
enum {ConIn,ConOut,ErrOut,EfiBltVideoFill};
EFI_GUID gEfiGraphicsOutputProtocolGuid, gMyronBootEntryHobGuid, gEfiEndOfDxeEventGroupGuid;
EFI_DEVICE_PATH_PROTOCOL KeypadDevicePath,DisplayDevicePath;
typedef struct {UINT8 Blue,Green,Red,Reserved;} EFI_GRAPHICS_OUTPUT_BLT_PIXEL;
typedef struct {UINT32 HorizontalResolution,VerticalResolution;} INFO;
typedef struct {INFO *Info;} MODE;
typedef struct GOP GOP;
struct GOP { EFI_STATUS (*Blt)(GOP*,EFI_GRAPHICS_OUTPUT_BLT_PIXEL*,int,UINTN,UINTN,UINTN,UINTN,UINTN,UINTN,UINTN); MODE *Mode; };
typedef GOP EFI_GRAPHICS_OUTPUT_PROTOCOL;
struct BS {EFI_STATUS (*LocateProtocol)(EFI_GUID*,VOID*,VOID**); EFI_STATUS (*InstallConfigurationTable)(EFI_GUID*,VOID*);};
static INFO info={1200,2608}; static MODE mode={&info}; static GOP gop;
static struct BS bs; static struct BS *gBS=&bs;
static jmp_buf stop;
static int stop_at, calls[32], count, missing_gop, bad_blt, load_error, draws;
static UINT8 pixels[288][288];
static VOID checkpoint(int id) {calls[count++]=id;if(stop_at==id)longjmp(stop,1);}
static EFI_STATUS locate(EFI_GUID*a,VOID*b,VOID**out){*out=missing_gop?NULL:&gop;return missing_gop;}
static EFI_STATUS table(EFI_GUID*a,VOID*b){checkpoint(10);return 0;}
static EFI_STATUS blt(GOP*g,EFI_GRAPHICS_OUTPUT_BLT_PIXEL*p,int op,UINTN sx,UINTN sy,UINTN x,UINTN y,UINTN w,UINTN h,UINTN d){
 assert(op==EfiBltVideoFill); assert(x+w<=info.HorizontalResolution && y+h<=info.VerticalResolution);
 if(bad_blt)return 1;
 if(y>=208){
  assert(x>=32&&x+w<=288&&y+h<=288);draws++;
  for(UINTN row=y;row<y+h;row++)for(UINTN col=x;col<x+w;col++)pixels[row][col]=p->Red;
 }
 return 0;
}
static VOID *GetFirstGuidHob(EFI_GUID*g){return &gMyronBootEntryHobGuid;}
static VOID EfiEventGroupSignal(EFI_GUID*g){checkpoint(1);}
static VOID EfiBootManagerDispatchDeferredImages(VOID){checkpoint(2);}
static VOID EfiBootManagerUpdateConsoleVariable(int c,EFI_DEVICE_PATH_PROTOCOL*p,VOID*n){checkpoint(3+c);}
static VOID EfiBootManagerConnectAll(VOID){checkpoint(11);}
VOID MyronAddBootMemory(VOID){checkpoint(12);}
VOID MyronAuditHandoff(VOID){checkpoint(13);}
VOID MyronPublishEmbeddedPayload(VOID){checkpoint(14);}
static VOID Print(const wchar_t *s,...){if(wcsstr(s,L"R64"))checkpoint(15);}
static EFI_STATUS MyronStartUniXNU(VOID){checkpoint(16);return load_error;}
static VOID CpuDeadLoop(VOID){assert(!"Unexpected deadloop");}
#include "bds-under-test.c"
static VOID reset(VOID){mStarted=0;mBdsPhase=0;count=0;draws=0;stop_at=0;missing_gop=0;bad_blt=0;load_error=0;memset(pixels,0,sizeof pixels);info.HorizontalResolution=1200;info.VerticalResolution=2608;}
int main(VOID){
 gop.Blt=blt;gop.Mode=&mode;bs.LocateProtocol=locate;bs.InstallConfigurationTable=table;
 int ids[]={1,2,3,4,5,10,11,12,13,14,15,16};
 UINT16 phases[]={0xB001,0xB002,0xB003,0xB004,0xB005,0xB010,0xB011,0xB012,0xB013,0xB014,0xB015,0xB016};
 for(volatile unsigned i=0;i<sizeof ids/sizeof ids[0];i++){
  reset();stop_at=ids[i];
  if(setjmp(stop)==0){PlatformBootManagerBeforeConsole();PlatformBootManagerAfterConsole();assert(!"expected injected stall");}
  assert(mBdsPhase==phases[i]);assert(draws>0);
  /* B glyph's upper-left white and upper-right black cells at scale 16. */
  assert(pixels[208][32]==255 && pixels[208][64]==0);
 }
 reset();PlatformBootManagerBeforeConsole();assert(mBdsPhase==0xB006);PlatformBootManagerAfterConsole();assert(mBdsPhase==0xB017);
 assert(count==12);assert(!memcmp(calls,ids,sizeof ids));
 PlatformBootManagerAfterConsole();assert(count==12); /* No second launch. */
 reset();load_error=1;PlatformBootManagerAfterConsole();assert(mBdsPhase==0xB0FF);
 /* Drawing failures never prevent the original boot flow, and never write out of bounds. */
 for(int test=0;test<5;test++){
  reset();if(test==0)missing_gop=1;if(test==1)bad_blt=1;if(test==2)info.HorizontalResolution=287;if(test==3)info.VerticalResolution=287;if(test==4)gop.Blt=NULL;
  /* BeforeConsole's historical green stripe requires a usable GOP.Blt; renderer is independently optional. */
  MyronBdsPhase(0xB001);assert(mBdsPhase==0xB001);assert(draws==0);
  if(test!=4){PlatformBootManagerAfterConsole();assert(mBdsPhase==0xB017);}
  gop.Blt=blt;
 }
 puts("BDS source: 12 injected stalls, original call order, one-shot launch, error return and 5 display failures passed");
 return 0;
}
