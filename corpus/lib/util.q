/ generic helpers
\d .util
clamp:{[lo;hi;x] lo|hi&x}
mean:{sum[x]%count x}
pad:{[n;s] n$string s}
\d .
