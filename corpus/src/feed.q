\l src/schema.q
\l lib/log.q
upd:{[t;x] t insert x; .log.info "upd"}
.feed.tick:{upd[`trade;(.z.p;`MSFT;2.5;10)]}
.feed.start:{.log.info "start"; .feed.tick[]}
.z.ts:{.feed.tick[]}
