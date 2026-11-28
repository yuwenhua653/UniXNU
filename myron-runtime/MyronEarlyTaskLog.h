// SPDX-License-Identifier: MIT
// Unauthenticated console hints only; never used to authorize disk writes.
// All accesses hold console_capture_busy. Keep the first 12 and last 4 tagged
// lines independently of the noisy console tail, including after scanout.
static char early_task_line[192], early_task_first[12][192], early_task_tail[4][192];
static unsigned early_task_used, early_task_overflow, early_task_skip;
static uint64_t early_task_count, early_task_truncated, early_task_gaps;
static int early_task_prefix(const char *line,const char *prefix) {
 while(*prefix)if(*line++!=*prefix++)return 0;
 return 1;
}
static void early_task_gap(void) {
 early_task_used=0;early_task_overflow=0;early_task_skip=1;++early_task_gaps;
}
static void early_task_char(char c) {
 if(c=='\r')return;
 if(early_task_skip){if(c=='\n')early_task_skip=0;return;}
 if(c!='\n') {
  if(c=='\t')c=' ';
  if(c<32 || c>126){early_task_skip=1;early_task_used=0;early_task_overflow=0;return;}
  if(early_task_used<sizeof(early_task_line)-1)early_task_line[early_task_used++]=c;
  else early_task_overflow=1;
  return;
 }
 early_task_line[early_task_used]=0;
 if(early_task_prefix(early_task_line,"[myron-data-earlyboot] ") ||
    early_task_prefix(early_task_line,"[myron-apfs-grow] ")) {
  if(early_task_overflow){++early_task_truncated;early_task_line[188]='.';early_task_line[189]='.';early_task_line[190]='.';}
  char *row=early_task_count<12?early_task_first[early_task_count]:early_task_tail[(early_task_count-12)%4];
  for(unsigned i=0;i<=early_task_used;++i)row[i]=early_task_line[i];
  ++early_task_count;
 }
 early_task_used=0;early_task_overflow=0;
}
