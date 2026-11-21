/* SPDX-License-Identifier: GPL-2.0-only */
#include "MyronFT3683.h"
#include "MyronTouchBoard.h"
#include "MyronTouchPower.h"
#include "fts_myron_frame.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

struct controller {
    uint8_t id[2], mode, data[MYRON_FRAME_BYTES], report[MYRON_REPORT_BYTES];
    unsigned writes, calls, reports;
    int bad_crc, bad_status, reject;
};
static void wait_us(void *p, unsigned n) { (void)p; assert(n > 0); }
static int transfer(void *p, const uint8_t *tx, uint8_t *rx, size_t n)
{
    struct controller *c = p;
    unsigned size = tx[2]*256u + tx[3];
    c->calls++;
    if (c->bad_status) { rx[3] = 0x80; return 0; }
    if (!tx[1]) {
        assert(tx[0]==0x9e && n==8 && size==1 && tx[7]==0);
        c->writes++; c->mode=tx[7]; return 0;
    }
    assert(tx[1]==0xa0 && n==size+9);
    switch (tx[0]) {
    case 1: assert(size==MYRON_FRAME_BYTES); memcpy(rx+7,c->data,size); break;
    case 0xa3: rx[7]=c->id[0]; break;
    case 0x9f: rx[7]=c->id[1]; break;
    case 0x9e: rx[7]=c->mode; break;
    default: assert(0);
    }
    uint16_t crc = fts_myron_crc(rx+7,size);
    rx[7+size]=(uint8_t)(crc ^ c->bad_crc); rx[8+size]=(uint8_t)(crc>>8);
    return 0;
}
static int submit(void *p, const uint8_t *data, size_t n)
{
    struct controller *c=p;
    assert(n==MYRON_REPORT_BYTES && data[0]==3);
    if (c->reject) return -EIO;
    memcpy(c->report,data,n);
    c->reports++;
    return 0;
}
static void point(uint8_t *p, unsigned flag, unsigned id, unsigned x, unsigned y)
{
    x*=16; y*=16;
    p[0]=(uint8_t)((flag<<6)|(x>>12)); p[1]=(uint8_t)(x>>4);
    p[2]=(uint8_t)((id<<4)|(y>>12)); p[3]=(uint8_t)(y>>4);
    p[4]=(uint8_t)((x<<4)|(y&15));
}
struct wires { unsigned cs,clk,mosi,bits,reads,cs_edges, settled; uint16_t sent; };
static uint32_t read_miso(void *p, enum myron_pin pin, unsigned off)
{
    struct wires *w=p;
    assert(w->settled);
    assert(pin==MISO && off==4 && w->cs==0 && w->clk==2 && w->bits==w->reads+1);
    return (0x9643u >> (15-w->reads++))&1;
}
static void write_wire(void *p, enum myron_pin pin, unsigned off, uint32_t v)
{
    struct wires *w=p; assert(off==4 && (v==0 || v==2));
    if (pin==CS) { assert(w->cs!=v && !w->clk); w->cs=v; w->cs_edges++; return; }
    assert(!w->cs);
    if (pin==MOSI) { assert(!w->clk); w->mosi=v; return; }
    assert(pin==SCLK && w->clk!=v);
    if (v) { w->sent=(uint16_t)(w->sent*2+(w->mosi!=0)); w->bits++; }
    w->clk=v; w->settled=0;
}
static void wire_wait(void *p, unsigned us)
{
    struct wires *w = p;
    assert(us);
    if (w->clk) w->settled=1;
}

static void wire_edge(void *p) { wire_wait(p,1); }

/* Walk the descriptor as a HID consumer would and verify report wire sizes. */
static void descriptor(void)
{
    unsigned id=0, size=0, count=0, page=0, usage=0, depth=0, fingers=0;
    unsigned input_bits=0, feature_bits=0, x=0, y=0, tips=0, valid=0;
    for (size_t i=0; i<myron_touch_descriptor_bytes;) {
        uint8_t tag=myron_touch_descriptor[i++];
        unsigned length=tag&3, v=0;
        if (length==3) length=4;
        assert(i+length<=myron_touch_descriptor_bytes);
        for (unsigned j=0; j<length; ++j) v|=(unsigned)myron_touch_descriptor[i++]<<(8*j);
        switch (tag&0xfc) {
        case 0x04: page=v; break;
        case 0x08: usage=v; break;
        case 0x84: id=v; break;
        case 0x74: size=v; break;
        case 0x94: count=v; break;
        case 0xa0:
            if (!depth) assert(page==13 && usage==4 && v==1);
            else { assert(page==13 && usage==0x22 && v==2); ++fingers; }
            ++depth; break;
        case 0xc0: assert(depth); --depth; break;
        case 0x80:
            assert(id==3); input_bits+=size*count;
            if ((v&1)==0 && page==1 && usage==0x30) ++x;
            if ((v&1)==0 && page==1 && usage==0x31) ++y;
            if ((v&1)==0 && page==13 && usage==0x42) ++tips;
            if (!(v&1) && page==13 && usage==0x37) {
                assert(size==1 && count==1 && (input_bits-1)%48==2);
                ++valid;
            }
            break;
        case 0xb0: assert(id==4 && page==13 && usage==0x55); feature_bits+=size*count; break;
        }
    }
    assert(!depth && fingers==10 && x==10 && y==10 && tips==10 && valid==10);
    assert(input_bits==8*(MYRON_REPORT_BYTES-1) && feature_bits==8);
}
/* Model the stock AP DRV2 layout and independent completion of its commands. */
struct rail_model {
    uint32_t regs[0x2000/4];
    int result;
    unsigned writes, commands;
};
enum { RSC_TCS = 0xd00, RSC_ACTIVE2 = RSC_TCS + 2*0x2a0 };
static uint32_t rail_read(void *p, unsigned off) {
    struct rail_model *m=p;
    assert(off < sizeof m->regs && !(off & 3));
    return m->regs[off/4];
}
static void rail_write(void *p, unsigned off, uint32_t value) {
    struct rail_model *m=p;
    assert(off < sizeof m->regs && !(off & 3));
    ++m->writes;
    m->regs[off/4]=value;
    if (off == RSC_TCS+8) m->regs[(RSC_TCS+4)/4] &= ~value;
    unsigned legacy = (m->regs[0] >> 16) == 2;
    unsigned ctrl = legacy ? 0x14 : 0x24;
    if (off != RSC_ACTIVE2+ctrl || value != 0x1010000) return;
    const unsigned address[3]={0x41230,0x41238,0x41234}, data[3]={1800,5,1};
    assert(rail_read(m,RSC_ACTIVE2+ctrl+8)==7 && rail_read(m,RSC_ACTIVE2+ctrl-4)==7);
    for (unsigned c=0;c<3;++c) {
        unsigned cmd=RSC_ACTIVE2+(legacy ? 0x30+20*c : 0x34+24*c);
        assert(rail_read(m,cmd)==0x10108);
        assert(rail_read(m,cmd+4)==address[c] && rail_read(m,cmd+8)==data[c]);
        ++m->commands;
        m->regs[(cmd+12)/4]=(c==1 && m->result==MYRON_POWER_RESPONSE) ? 0x100 : 0x10100;
    }
    if (m->result!=MYRON_POWER_TIMEOUT) m->regs[(RSC_TCS+4)/4] |= 4;
}
static void test_io_supply(void) {
    uint32_t db[64]={0};
    db[1]=0x0c0330db; db[2]=4; db[3]=1u<<16;
    db[36]=0x5f49344c; db[37]=0x3045; db[40]=0x41230;
    assert(myron_l4i_address(db,sizeof db)==0x41230);
    assert(!myron_l4i_address(db,167));
    db[37]++; assert(!myron_l4i_address(db,sizeof db)); db[37]--;
    db[2]=3; assert(!myron_l4i_address(db,sizeof db)); db[2]=4;
    memcpy(db+42,db+36,24); db[3]=2u<<16; assert(!myron_l4i_address(db,sizeof db));
    for (unsigned major=2;major<=4;++major) {
        struct rail_model m={0};
        struct myron_rsc_io io={&m,rail_read,rail_write,wait_us};
        m.regs[0]=(major<<16) | (7u<<8);
        m.regs[3]=(31u<<27) | (8u<<12);
        m.regs[(RSC_ACTIVE2+(major==2 ? 0x18 : 0x28))/4]=1;
        assert(myron_vote_l4i(&io,0x41230)==MYRON_POWER_OK && m.commands==3);
        if (major >= 3) {
            m.regs[(RSC_TCS+0x2c)/4]=1u<<25;
            m.regs[(RSC_TCS+0x38+25*24)/4]=0x41000;
            assert(myron_vote_l4i(&io,0x41230)==MYRON_POWER_OK && m.commands==6);
            m.regs[(RSC_TCS+0x38+25*24)/4]=0x41238;
            unsigned before=m.writes;
            assert(myron_vote_l4i(&io,0x41230)==MYRON_POWER_BUSY && m.writes==before);
        }
        unsigned before=m.writes;
        m.regs[(RSC_TCS+(major==2 ? 0x1c : 0x2c))/4]=1u<<31;
        assert(myron_vote_l4i(&io,0x41230)==MYRON_POWER_BUSY && m.writes==before);
    }
    const unsigned badConfig[]={0,0xffffffffu,(2u<<27)|(8u<<12),(16u<<27)|(2u<<12)};
    for (unsigned i=0;i<sizeof badConfig/sizeof badConfig[0];++i) {
        struct rail_model m={0};
        struct myron_rsc_io io={&m,rail_read,rail_write,wait_us};
        m.regs[0]=3u<<16;
        m.regs[3]=badConfig[i];
        assert(myron_vote_l4i(&io,0x41230)==MYRON_POWER_LAYOUT && !m.writes);
    }
    for (int code=MYRON_POWER_OK;code<=MYRON_POWER_RESPONSE;++code) {
        struct rail_model m={.result=code};
        struct myron_rsc_io bus={&m,rail_read,rail_write,wait_us};
        m.regs[0]=(code==MYRON_POWER_LAYOUT ? 1u : 3u)<<16;
        m.regs[3]=(16u<<27) | (8u<<12);
        m.regs[RSC_TCS/4]=0x20;
        for (unsigned i=0;i<3;++i) m.regs[(RSC_TCS+0x2a0*i+0x28)/4]=1;
        if (code==MYRON_POWER_BUSY) {
            m.regs[(RSC_TCS+0x2c)/4]=1;
            m.regs[(RSC_TCS+0x38)/4]=0x41234;
        }
        assert(myron_vote_l4i(&bus,code==MYRON_POWER_DB ? 0 : 0x41230)==code);
        if (code==MYRON_POWER_DB || code==MYRON_POWER_LAYOUT || code==MYRON_POWER_BUSY)
            assert(!m.writes && !m.commands);
        else {
            assert(m.commands==3 && rail_read(&m,RSC_TCS)==0x20);
            if (code==MYRON_POWER_OK) {
                assert(rail_read(&m,RSC_ACTIVE2+0x24)==0);
                assert(myron_vote_l4i(&bus,0x41230)==MYRON_POWER_OK && m.commands==6);
            }
            assert(rail_read(&m,RSC_ACTIVE2+0x2c)==(code==MYRON_POWER_TIMEOUT ? 7u : 0u));
        }
    }
}

int main(void)
{
    test_io_supply();
    descriptor();
    struct wires wires={.cs=2};
    struct myron_gpio_io io={&wires,read_miso,write_wire,wire_wait,wire_edge};
    uint8_t tx[]={0x81,0x3f},rx[2];
    assert(myron_spi_transfer(&io,tx,rx,2)==0 && wires.cs_edges==2 && wires.bits==16);
    assert(rx[0]==0x96 && rx[1]==0x43 && wires.sent==0x813f && wires.clk==0 && wires.cs==2);
    assert(fts_myron_crc((const uint8_t *)"123456789",9)==0x6f91);
    struct controller c={.id={0x36,0x83},.mode=0xaa};
    struct myron_touch t={.bus={&c,transfer,wait_us}};
    c.id[0]=0; assert(myron_touch_identify_and_start(&t)==-ENODEV && !c.writes);
    c.id[0]=0x36; assert(myron_touch_identify_and_start(&t)==0 && t.ready && c.writes==1);
    c.data[1]=0x21;
    for (unsigned flag=0; flag<3; ++flag) {
        const unsigned sequence[]={0,2,1};
        point(c.data+4,sequence[flag],0,20,30);
        assert(!myron_touch_read_contacts(&t,submit,&c));
        assert(c.report[61]==1 && c.report[2]==0 && c.report[1]==(flag==2?6:7));
        for (unsigned i=1;i<MYRON_FINGERS;++i) assert(!(c.report[1+6*i]&4));
    }
    c.data[1]=0x22;
    point(c.data+4,0,7,1199,2607); point(c.data+12,0,1,0,0);
    assert(!myron_touch_read_contacts(&t,submit,&c) && c.report[61]==2 && c.report[2]==1);
    assert(c.report[7]==7 && c.report[8]==7 && t.x[7]>32730 && t.y[7]>32730);
    c.data[1]=0x21; point(c.data+4,2,7,600,1304);
    c.reject=1; assert(myron_touch_read_contacts(&t,submit,&c)==-EIO && t.active==130);
    c.reject=0; assert(!myron_touch_read_contacts(&t,submit,&c) && t.active==128);
    assert(c.report[1]==7 && c.report[2]==7 && c.report[7]==6 && c.report[8]==1);
    uint16_t last=t.x[7]; assert(last>=16383 && last<=16384);
    unsigned count=c.reports;
    c.data[1]=0x20;
    for (unsigned i=0; i<30; ++i) assert(!myron_touch_read_contacts(&t,submit,&c));
    assert(t.active==128 && c.reports==count);
    c.bad_crc=1; unsigned before=c.calls;
    assert(myron_touch_read_contacts(&t,submit,&c)==-EBADMSG && c.calls-before==3);
    c.bad_crc=0; c.bad_status=1;
    assert(myron_touch_read_contacts(&t,submit,&c)==-EIO && t.active==128 && c.reports==count);
    c.bad_status=0; c.data[1]=0x22; point(c.data+12,2,7,1,2);
    assert(myron_touch_read_contacts(&t,submit,&c)==-EBADMSG && c.reports==count);
    c.data[1]=0x21; point(c.data+4,1,7,0,0);
    assert(!myron_touch_read_contacts(&t,submit,&c) && !t.active && c.report[1]==6);
    assert((unsigned)(c.report[3]|c.report[4]<<8)==last && c.report[61]==1);
    memset(c.data,0xff,sizeof(c.data)); c.data[0]=0; c.data[1]=1;
    c.data[2]=0; c.data[3]=40; c.data[4]=0x40; c.data[5]=80;
    assert(!myron_touch_read_contacts(&t,submit,&c) && t.active==16);
    memset(c.data,0xff,sizeof(c.data));
    assert(!myron_touch_read_contacts(&t,submit,&c) && !t.ready && !t.active && c.report[1]==6);
    puts("PASS: SPI mode 0, probe, TIC readback, CRC, v1/v2 contacts, XY, two fingers, moves, lifts, dropped report, controller restart");
}
