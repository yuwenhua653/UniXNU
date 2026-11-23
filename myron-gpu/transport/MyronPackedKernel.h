// SPDX-License-Identifier: BSD-2-Clause-Patent
// Bounded, independent 64 KiB LZ4 blocks. This changes file transport only;
// KernelStream still validates/loads the original Mach-O and fileset members.
// Format: transport.py. LZ4 block spec: lz4/lz4 v1.10.0 doc/lz4_Block_format.md.
#ifndef MYRON_PACKED_KERNEL_H
#define MYRON_PACKED_KERNEL_H
#ifndef EFIAPI
#define EFIAPI
#endif
STATIC UINT32 MkCrc(CONST UINT8 *p, UINTN n) {
  UINT32 c=0xffffffffU; UINTN i; unsigned b;
  for(i=0;i<n;i++){c^=p[i];for(b=0;b<8;b++)c=(c>>1)^(0xedb88320U & (0U-(c&1)));}
  return ~c;
}
STATIC BOOLEAN MkLz4(CONST UINT8 *in,UINTN n,UINT8 *out,UINTN size) {
  UINTN p=0,q=0,l,m,offset,i; UINT8 token,v;
  while(p<n) {
    token=in[p++];l=token>>4;
    if(l==15){do{if(p==n)return FALSE;v=in[p++];if(v>size || l>size-v)return FALSE;l+=v;}while(v==255);}
    if(l>n-p || l>size-q)return FALSE;
    CopyMem(out+q,in+p,l);p+=l;q+=l;
    if(p==n)return q==size;
    if(n-p<2)return FALSE;
    offset=in[p]|((UINTN)in[p+1]<<8);p+=2;
    if(!offset || offset>q)return FALSE;
    m=(token&15)+4;
    if((token&15)==15){do{if(p==n)return FALSE;v=in[p++];if(v>size || m>size-v)return FALSE;m+=v;}while(v==255);}
    if(m>size-q)return FALSE;
    for(i=0;i<m;i++){out[q]=out[q-offset];q++;}
  }
  return FALSE; // A final literal sequence is mandatory.
}
STATIC EFI_STATUS MkPhysical(EFI_FILE_PROTOCOL *f,UINT64 limit,UINT64 at,UINTN n,VOID *out) {
  EFI_STATUS s;UINTN want,got,done=0;
  if(at>limit || n>limit-at || (n && !out))return EFI_BAD_BUFFER_SIZE;
  s=f->SetPosition(f,at);if(EFI_ERROR(s))return s;
  while(done<n){want=MIN(n-done,SIZE_64KB);got=want;s=f->Read(f,&got,(UINT8*)out+done);
    if(EFI_ERROR(s))return s;
    if(!got || got>want)return EFI_DEVICE_ERROR;
    done+=got;}
  return EFI_SUCCESS;
}
typedef struct {
  EFI_FILE_PROTOCOL File;
  EFI_FILE_PROTOCOL *Input;
  UINT64 Stored,Logical,Position;
  UINT32 Count,Cached;
  UINT8 *Index,*Packed,*Decoded;
} MK_FILE;
STATIC EFI_STATUS EFIAPI MkClose(EFI_FILE_PROTOCOL *file) {
  MK_FILE *f=(MK_FILE*)file;EFI_FILE_PROTOCOL *input=f->Input;
  FreePool(f->Index);FreePool(f->Packed);FreePool(f->Decoded);FreePool(f);
  return input->Close(input);
}
STATIC EFI_STATUS EFIAPI MkSeek(EFI_FILE_PROTOCOL *file,UINT64 at) {
  MK_FILE *f=(MK_FILE*)file;
  if(at==MAX_UINT64)at=f->Logical;
  if(at>f->Logical)return EFI_BAD_BUFFER_SIZE;
  f->Position=at;return EFI_SUCCESS;
}
STATIC EFI_STATUS EFIAPI MkRead(EFI_FILE_PROTOCOL *file,UINTN *bytes,VOID *out) {
  MK_FILE *f=(MK_FILE*)file;UINTN done=0,n,inside,take;UINT32 block,len,raw,flags;
  CONST UINT8 *row;EFI_STATUS s;
  if(!bytes)return EFI_BAD_BUFFER_SIZE;
  n=*bytes;*bytes=0;if(n && !out)return EFI_BAD_BUFFER_SIZE;
  n=(UINTN)MIN((UINT64)n,f->Logical-f->Position);
  while(done<n){
    block=(UINT32)(f->Position/SIZE_64KB);inside=(UINTN)(f->Position%SIZE_64KB);
    if(block>=f->Count)return EFI_COMPROMISED_DATA;
    row=f->Index+24*block;len=U32(row+8);raw=U32(row+12);flags=U32(row+20);
    if(f->Cached!=block){
      f->Cached=0xffffffffU;
      s=MkPhysical(f->Input,f->Stored,U64(row),len,f->Packed);if(EFI_ERROR(s))return s;
      if(flags==1){if(!MkLz4(f->Packed,len,f->Decoded,raw))return EFI_COMPROMISED_DATA;}
      else CopyMem(f->Decoded,f->Packed,raw);
      if(MkCrc(f->Decoded,raw)!=U32(row+16))return EFI_COMPROMISED_DATA;
      f->Cached=block;
    }
    take=MIN(n-done,raw-inside);CopyMem((UINT8*)out+done,f->Decoded+inside,take);
    done+=take;f->Position+=take;*bytes=done;
  }
  return EFI_SUCCESS;
}
STATIC EFI_STATUS MkOpen(EFI_FILE_PROTOCOL **file,UINTN *size) {
  UINT8 h[96];UINT64 logical,at,total;UINT32 count,i,len,raw,flags;
  MK_FILE *f=NULL;EFI_STATUS s;CONST UINT8 *row;
  if(*size<8)return EFI_LOAD_ERROR;
  s=MkPhysical(*file,*size,0,8,h);if(EFI_ERROR(s))return s;
  if(CompareMem(h,"MYRKERN1",8))return EFI_SUCCESS; // Existing plain Mach-O path.
  s=MkPhysical(*file,*size,0,sizeof(h),h);if(EFI_ERROR(s))return s;
  logical=U64(h+16);total=U64(h+24);count=U32(h+32);
  if(U32(h+8)!=1 || U32(h+12)!=SIZE_64KB || logical<32 || logical>SIZE_128MB ||
     total!=*size || count!=(logical+SIZE_64KB-1)/SIZE_64KB || U32(h+36)!=24)return EFI_COMPROMISED_DATA;
  for(i=76;i<96;i++)if(h[i])return EFI_COMPROMISED_DATA;
  at=96+(UINT64)count*24;if(at>total)return EFI_COMPROMISED_DATA;
  f=AllocatePool(sizeof(*f));if(!f)return EFI_OUT_OF_RESOURCES;ZeroMem(f,sizeof(*f));
  f->Index=AllocatePool(count*24);f->Packed=AllocatePool(SIZE_64KB);f->Decoded=AllocatePool(SIZE_64KB);
  s=EFI_OUT_OF_RESOURCES;if(!f->Index || !f->Packed || !f->Decoded)goto Fail;
  s=MkPhysical(*file,total,96,count*24,f->Index);if(EFI_ERROR(s))goto Fail;
  s=EFI_COMPROMISED_DATA;if(MkCrc(f->Index,count*24)!=U32(h+72))goto Fail;
  for(i=0;i<count;i++){
    row=f->Index+24*i;len=U32(row+8);raw=U32(row+12);flags=U32(row+20);
    if(U64(row)!=at || raw!=MIN((UINT64)SIZE_64KB,logical-(UINT64)i*SIZE_64KB) ||
       !len || len>raw || flags>1 || (!flags && len!=raw) || (flags && len>=raw) || len>total-at)goto Fail;
    at+=len;
  }
  if(at!=total)goto Fail;
  f->File.Read=MkRead;f->File.SetPosition=MkSeek;f->File.Close=MkClose;
  f->Input=*file;f->Stored=total;f->Logical=logical;f->Count=count;f->Cached=0xffffffffU;
  *file=&f->File;*size=(UINTN)logical;return EFI_SUCCESS;
Fail:
  if(f->Index)FreePool(f->Index);
  if(f->Packed)FreePool(f->Packed);
  if(f->Decoded)FreePool(f->Decoded);
  FreePool(f);
  return s;
}
#endif
