/ reflect.q - load q files in order inside a live q, emit JSON reflection.
/ env: QV_FILES (colon separated, load order), QV_OUT (output json path)
/ Ground truth for definitions + resolved global references (value f).
\d .qv
base:key `;
isns:{$[99h=type x;$[count x;`~first key x;0b];0b]}
ns:{[n] dd:(enlist `)_get `$".",string n;
  (`$(".",(string n),".") ,/: string key dd;value dd)}
allp:{[]
  d:get `.;
  r:(key d;value d);
  rest:ns each (key `) except base,`qv;
  $[count rest;(r[0],raze rest[;0];r[1],raze rest[;1]);r]}
fp:{$[100h=type x;last value x;200 sublist .Q.s1 x]}
snap:{p:allp[];(p 0)!fp each p 1}
b0:snap[]
ex:{@[{get x;1b};x;{0b}]}
ctxres:{[ctx;g] s:string g;$[("."=first s);g;ctx~`;g;`$".",(string ctx),".",s]}
kind:{$[x=100h;"lambda";x=98h;"table";x=99h;"dict";x within 101 112h;"function";x<0h;"atom";"value"]}
/ globals / symbol constants of a lambda including lambdas nested in its constants (value f does not descend)
glob:{[v] x:value v;g:(1_x 3) except `;cs:-1_4_x;ls:cs where 100h=type each cs;g,raze glob each ls}
syms:{[v] x:value v;cs:-1_4_x;ls:cs where 100h=type each cs;(distinct raze symc each cs),raze syms each ls}
symc:{$[-11h=type x;enlist x;11h=type x;x;`symbol$()]}
lam:{[v] x:value v;g:x 3;
  sc:distinct syms v;
  ctx:$[count g;first g;`];
  refs:distinct glob v;
  rr:{[c;s] r:ctxres[c;s];`raw`res`ex!(string s;string r;ex r)}[ctx] each refs;
  `params`locals`ctx`refs`symconst`src!(string each x 1;string each x 2;string ctx;rr;string each sc;last x)}
describe:{[nm;v] t:type v;
  e:`name`t`kind!(string nm;t;kind t);
  e:$[100h=t;e,lam v;98h=t;e,enlist[`cols]!enlist string each cols v;e];
  e}
safe:{[nm;v] @[describe[nm];v;{[nm;e] `name`t`kind`error!(string nm;0h;"unknown";e)}[nm]]}
ldf:{[f] @[{system "l ",x;(1b;"")};f;{(0b;x)}]}
loadone:{[f]
  b:snap[];r:ldf f;a:snap[];
  new:(key a) except key b;
  k:(key b) inter key a;
  ch:k where not b[k]~'a k;
  `file`ok`err`new`changed!(f;r 0;r 1;string each new;string each ch)}
run:{[]
  fs:":" vs getenv `QV_FILES;
  files:loadone each fs;
  p:allp[];
  keep:where not (p 0) in key b0;
  defs:safe'[(p 0) keep;(p 1) keep];
  out:`files`defs!(files;defs);
  (hsym `$getenv `QV_OUT) 0: enlist .j.j out;
  exit 0}
\d .
.qv.run[]
