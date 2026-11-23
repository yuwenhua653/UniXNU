#!/usr/bin/env python3
"""Compile the actual Turnip identity block and pinned kernel/user wire types."""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile
from userspace_contract import verify_abi


def check(root, references, cxx='c++'):
    driver=references/'NativeAdreno'
    contract=verify_abi(driver)
    patch=(root/'patches/mesa/turnip-darwin-kmd.patch').read_text()
    start=patch.index('+   device->dev_id.chip_id = info->chip_id;')
    end=patch.index('+   device->gmem_size =',start)
    block='\n'.join(line[1:] for line in patch[start:end].splitlines())
    start=patch.index('+static kern_return_t\n+dw_call(')
    end=patch.index('+/* Finds an admitted selector:',start)
    transport='\n'.join(line[1:] for line in patch[start:end].splitlines())
    with tempfile.TemporaryDirectory() as tmp:
        temp=Path(tmp)
        # The production patch stays syntactically valid after changing a hunk.
        subprocess.run(['git','apply','--numstat',str(root/'patches/mesa/turnip-darwin-kmd.patch')],
                       check=True,stdout=subprocess.DEVNULL)
        (temp/'main.cpp').write_text('''#include <cassert>
#include <cstddef>
#include <cstring>
#include <initializer_list>
#include "NativeAdrenoABI.h"
static_assert(NativeAdrenoAbiMaxBuffers==128,"same kernel and Turnip submission capacity");
static_assert(sizeof(NativeAdrenoAbiSubmit)==3104,"whole 128-IB command record");
static_assert(offsetof(NativeAdrenoAbiSubmit,buffers)==32,"wire buffer offset");
static_assert(sizeof(NativeAdrenoAbiDeviceInfo)==64,"wire identity");
struct Device {struct {uint32_t chip_id,gpu_id;} dev_id;};
static Device identify(uint32_t chip) {Device result{};Device *device=&result;
NativeAdrenoAbiDeviceInfo data{};data.chip_id=chip;auto *info=&data;
'''+block+'''
return result;}
using kern_return_t=int;
constexpr int KERN_SUCCESS=0,kIOReturnUnderrun=-20,kIOReturnBadArgument=-21;
constexpr uint32_t DW_TUNNEL_MAGIC=0x4e544e4c;
struct {bool tunnel;unsigned conn,selector;} dw;
unsigned transportCalls=0;int transportStatus=0;bool shortReply=false;
NativeAdrenoAbiSubmit submission{};
int IOConnectCallStructMethod(unsigned,uint32_t selector,const void *in,size_t is,void *,size_t *os){
 ++transportCalls;
 if(dw.tunnel){
  assert(selector==9 && is==sizeof submission+8);
  const auto *p=static_cast<const uint32_t *>(in);
  assert(p[0]==DW_TUNNEL_MAGIC && p[1]==NativeAdrenoMethodSubmit);
  assert(memcmp(p+2,&submission,sizeof submission)==0);
 }else{assert(selector==NativeAdrenoMethodSubmit && is==sizeof submission);}
 if(shortReply && os)--*os;
 return transportStatus;
}
'''+transport+'''
int main(){
 assert(identify(0x43050a01).dev_id.gpu_id==740);
 for(unsigned slices=1;slices<=7;++slices){
  uint32_t chip=0x44050a01|(slices<<4);auto d=identify(chip);
  assert(d.dev_id.gpu_id==840 && d.dev_id.chip_id==chip);
 }
 assert(identify(0x06030001).dev_id.gpu_id==630);
 assert(identify(0x44060a31).dev_id.gpu_id!=840);
 assert(identify(0xffffffff).dev_id.gpu_id!=840);
 submission.buffer_count=128;
 NativeAdrenoAbiSubmitReply reply{};
 for(bool tunnel:{false,true}){
  dw.tunnel=tunnel;dw.selector=9;
  shortReply=false;transportStatus=0;
  assert(dw_call(NativeAdrenoMethodSubmit,&submission,sizeof submission,&reply,sizeof reply)==0);
  shortReply=true;
  assert(dw_call(NativeAdrenoMethodSubmit,&submission,sizeof submission,&reply,sizeof reply)==kIOReturnUnderrun);
  transportStatus=-33;
  assert(dw_call(NativeAdrenoMethodSubmit,&submission,sizeof submission,&reply,sizeof reply)==-33);
 }
 unsigned before=transportCalls;
 assert(dw_call(NativeAdrenoMethodSubmit,&submission,sizeof submission+1,&reply,sizeof reply)==kIOReturnBadArgument);
 assert(transportCalls==before);
}
''')
        subprocess.run([cxx,'-std=c++17','-Wall','-Wextra','-Werror','-Wunused-const-variable','-I',str(driver),
                        str(temp/'main.cpp'),'-o',str(temp/'check')],check=True)
        subprocess.run([str(temp/'check')],check=True)
        (temp/'NativeAdrenoABI.h').write_bytes((driver/'NativeAdrenoABI.h').read_bytes()+b'\n')
        try:verify_abi(temp)
        except ValueError:pass
        else:raise AssertionError('Changed kernel/user ABI was accepted')
    return contract


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--references',type=Path,required=True)
    p.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[2]);p.add_argument('--cxx',default='c++')
    a=p.parse_args();print(json.dumps(check(a.root.resolve(),a.references.resolve(),a.cxx)))
