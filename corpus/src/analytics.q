\l lib/util.q
\l lib/log.q
\l src/schema.q
\d .an
vwap:{[t] select vwap:qty wavg px by sym from t}
spread:{[q] select sym, s:ask-bid from q}
norm:{[x] .util.clamp[0;1;(x-min x)%max[x]-min x]}
avgpx:{.util.mean exec px from trade}
report:{.log.info "report"; v:vwap[`trade]; s:spread[`quote]; (v;s)}
rebuild:{.log.info "rb"; helperMissing[1]}
dyn:{[nm] value "." , string[nm], "[1]"}
means:{.util.mean each x}
\d .
