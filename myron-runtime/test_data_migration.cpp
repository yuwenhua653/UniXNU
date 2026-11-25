// SPDX-License-Identifier: BSD-2-Clause-Patent
#include <array>
#include <cassert>
#include <map>
#include <memory>
#include <cstdio>
#include "MyronDataMigration.h"
using Page=std::array<unsigned char,4096>;
using Result=MyronDataMigrationResult;
static const MyronRootGeometry phone={249424640,257813247,257813503,34241249280ULL,117911552,28928};
static constexpr uint64_t rootBytes=15092154368ULL, dest=256473556ULL, source=257522166ULL;
static const unsigned char seed[32]={1};
struct Store {
 std::map<uint64_t,Page> disk;
 unsigned calls=0,failAt=0,writes=0,checks=0,corruptReadAt=0;
 bool offline=true,changeSource=false;
 bool quiescent(){++checks;return offline;}
 bool step(){return ++calls!=failAt;}
 bool read(uint64_t first,uint32_t n,void *out){
  assert(n && n<=32);
  assert((first>=dest && first+n<=dest+MyronDataGrownBlocks) ||
         (first>=source && first+n<=source+MyronDataOldBlocks));
  if(!step())return false;
  auto p=static_cast<unsigned char*>(out);
  for(unsigned i=0;i<n;++i){auto it=disk.find(first+i);if(it==disk.end())memset(p+i*4096,0,4096);else memcpy(p+i*4096,it->second.data(),4096);}
  if(calls==corruptReadAt)p[0]^=1;
  return true;
 }
 bool write(uint64_t first,uint32_t n,const void *in){
  // All writes, including injected failures and retries, stay in the new copy.
  assert(n && n<=32 && first>=dest && first+n<=dest+MyronDataGrownBlocks && first+n<=source);
  if(!step())return false;
  ++writes;auto p=static_cast<const unsigned char*>(in);
  for(unsigned i=0;i<n;++i)memcpy(disk[first+i].data(),p+i*4096,4096);
  if(changeSource && first==dest+1)disk[source+2][0]^=8;
  return true;
 }
 bool sync(){return step();}
};
static Store original(){
 Store s;myronDataMark(s.disk[source].data(),source,MyronDataOldBlocks,2);
 auto &h=s.disk[source+1];memcpy(h.data(),"SHNGDATA",8);myronDataPut(h.data()+8,1,4);
 myronDataPut(h.data()+12,64,4);myronDataPut(h.data()+16,MyronDataSeedBytes/4096,8);
 memcpy(h.data()+24,seed,32);myronDataPut(h.data()+60,myronDataCrc(h.data(),60),4);
 // Exercise a run split at 32 pages, a gap, and the final source page.
 for(unsigned i=0;i<33;++i){s.disk[source+2+i/(4096*8)][(i/8)%4096]|=1u<<(i%8);s.disk[source+10+i].fill((unsigned char)(i+1));}
 constexpr unsigned last=MyronDataSeedBytes/4096-1;
 s.disk[source+2+last/(4096*8)][(last/8)%4096]|=1u<<(last%8);s.disk[source+10+last].fill(99);
 return s;
}
static void oldUnchanged(const Store &s,const Store &old){
 for(const auto &p:old.disk)assert(s.disk.at(p.first)==p.second);
 for(const auto &p:s.disk)if(p.first>=source)assert(old.disk.count(p.first));
}
static unsigned marker(const Store &s){auto it=s.disk.find(dest);return it==s.disk.end()?0:myronDataGrowthMarker(it->second.data(),dest);}
int main(){
 auto scratch=std::make_unique<MyronDataMigrationScratch>();Store old=original(),s=old;
 assert(myronDataMigrate(s,phone,rootBytes,seed,*scratch)==Result::Ready);oldUnchanged(s,old);
 unsigned operations=s.calls;assert(marker(s)==2 && myronDataGrowthHeader(s.disk.at(dest+1).data(),seed));
 for(unsigned i=0;i<33;++i)assert(s.disk.at(dest+34+i)==old.disk.at(source+10+i));
 assert(s.disk.at(dest+34+MyronDataSeedBytes/4096-1)==old.disk.at(source+10+MyronDataSeedBytes/4096-1));
 for(unsigned i=8;i<32;++i)for(auto b:s.disk.at(dest+2+i))assert(!b);
 unsigned writes=s.writes;assert(myronDataMigrate(s,phone,rootBytes,seed,*scratch)==Result::AlreadyReady && s.writes==writes);
 // Fail every storage operation; a partial copy can be retried, but a ready
 // marker (even if its final sync/read failed) must never be copied over.
 for(unsigned op=1;op<=operations;++op){
  s=old;s.failAt=op;assert(myronDataMigrate(s,phone,rootBytes,seed,*scratch)==Result::IOFailed);oldUnchanged(s,old);
  unsigned state=marker(s);assert(state==0 || state==1 || state==2);
  s.failAt=0;s.calls=0;
  assert(myronDataMigrate(s,phone,rootBytes,seed,*scratch)==(state==2?Result::AlreadyReady:Result::Ready));oldUnchanged(s,old);
 }
 s=old;s.offline=false;assert(myronDataMigrate(s,phone,rootBytes,seed,*scratch)==Result::Refused && !s.calls);
 s=old;s.disk[source+1][24]^=1;assert(myronDataMigrate(s,phone,rootBytes,seed,*scratch)==Result::SourceInvalid && !s.writes);
 s=old;s.disk[dest][0]=7;assert(myronDataMigrate(s,phone,rootBytes,seed,*scratch)==Result::DestinationInvalid && !s.writes);
 s=old;myronDataMark(s.disk[dest].data(),dest,MyronDataGrownBlocks,2);s.disk[dest][32]^=1;
 assert(myronDataMigrate(s,phone,rootBytes,seed,*scratch)==Result::DestinationInvalid && !s.writes);
 s=old;s.changeSource=true;assert(myronDataMigrate(s,phone,rootBytes,seed,*scratch)==Result::SourceChanged && marker(s)==1);
 // First destination page readback follows 4 metadata reads, pending write,
 // sync, pending readback, source page read and page write.
 s=old;s.corruptReadAt=10;
 assert(myronDataMigrate(s,phone,rootBytes,seed,*scratch)==Result::ReadbackFailed && marker(s)==1);oldUnchanged(s,old);
 MyronDataSelection selected={};
 s=old;assert(myronDataSelect(s,phone,rootBytes,seed,scratch->data,selected));
 assert(selected.logicalBytes==MyronDataSeedBytes && selected.markerLba==source && !s.writes);
 myronDataMark(s.disk[dest].data(),dest,MyronDataGrownBlocks,1);
 assert(myronDataSelect(s,phone,rootBytes,seed,scratch->data,selected) && selected.markerLba==source);
 assert(myronDataMigrate(s,phone,rootBytes,seed,*scratch)==Result::Ready);
 assert(myronDataSelect(s,phone,rootBytes,seed,scratch->data,selected));
 assert(selected.logicalBytes==MyronDataGrownBytes && selected.markerLba==dest);
 // A valid old source is NOT a fallback after the destination was committed.
 s.disk[dest+1][24]^=1;
 assert(!myronDataSelect(s,phone,rootBytes,seed,scratch->data,selected));
 printf("PASS: pre-mount migration, %u injected I/O failures with retries, copy verification and fail-closed selection; no APFS resize\n",operations);
}
