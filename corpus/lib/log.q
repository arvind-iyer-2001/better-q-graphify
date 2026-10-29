\d .log
level:`info
msg:{[l;m] -1 string[l]," ",m}
info:{msg[`info;x]}
err:{msg[`err;x]; 'x}
unusedlog:{msg[`dbg;x]}
\d .
