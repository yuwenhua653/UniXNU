# Wallpaper crash attribution and pending diagnostics

The static library index from successful run 44995454249 was downloaded and
verified against artifact SHA256
`1316080591d5c222bbb7ffe956f5528a71f4d16ec88d49aa7229c39d530368ae`.
It describes the pinned iPhone12,1 / 24A446 cache. Combining its image ranges
with the same-boot recorded cache slide places the repeated wallpaper trap in
PosterBoard.framework, UUID `2ce463af35a63164ac6cb7a007e81d10`, at image offset
`0x266858`, with subsequent frames at `0x6be84` and `0x6a4b0`.

This is image-range attribution, not a function-level diagnosis or proof of
why it trapped. The old index does not include this framework's private symbol
table. Do not label a nearest export as the crashing function or replace the
trap with a return. The next static index recipe adds three UUID-bound,
function-bounded queries with exact-start names and nearby branch/string
references. It emits no raw image bytes and takes no user Data as input.
The query parser's tests pass; the new donor-image query has not run yet.

The separate CoreAnimation ColorAttachment rejection also lacks the actual
attachment descriptor in its current crash text. The resolved Metal frontend
now includes formats, masks, blend factors, sample count and rasterization in
the failed-pipeline NSError, bounded to 512 descriptor characters and only
constructed on refusal. It does not enable a disk journal or shader dump,
disable validation, or substitute a different color format. This requires the
next userspace component build; it is diagnostic coverage, not a wallpaper fix.
