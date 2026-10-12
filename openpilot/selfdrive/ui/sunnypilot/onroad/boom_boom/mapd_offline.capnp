# The offline map format of pfeiferj's mapd (https://github.com/pfeiferj/openpilot-mapd), v1.12.0
# offline.capnp, with its Go-only annotations removed so Python can load it. Read-only use by the
# boom-boom mini-map (osm_roads.py); mapd writes these files, nothing here does.
#
# Copyright 2023 Jacob Pfeifer. MIT License:
# Permission is hereby granted, free of charge, to any person obtaining a copy of this software and
# associated documentation files (the "Software"), to deal in the Software without restriction,
# including without limitation the rights to use, copy, modify, merge, publish, distribute,
# sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions: The above copyright notice and this
# permission notice shall be included in all copies or substantial portions of the Software.
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT
# NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
# NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES
# OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN
# CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

@0xda3a0d9284ca402f;

struct Way {
  name @0 :Text;
  ref @1 :Text;
  maxSpeed @2 :Float64;
  minLat @3 :Float64;
  minLon @4 :Float64;
  maxLat @5 :Float64;
  maxLon @6 :Float64;
  nodes @7 :List(Coordinates);
  lanes @8 :UInt8;
  advisorySpeed @9 :Float64;
  hazard @10 :Text;
  oneWay @11 :Bool;
  maxSpeedForward @12 :Float64;
  maxSpeedBackward @13 :Float64;
}

struct Coordinates {
  latitude @0 :Float64;
  longitude @1 :Float64;
}

struct Offline {
  minLat @0 :Float64;
  minLon @1 :Float64;
  maxLat @2 :Float64;
  maxLon @3 :Float64;
  ways @4 :List(Way);
  overlap @5 :Float64;
}
