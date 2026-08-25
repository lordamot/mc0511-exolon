# Work guideline

## General

All discussions in english.
All code except text strings must be in english.

## Project

Never work outside repository root. Binaries required must be built in tmp/ subfolder,
and then moved under bin/ subfolder - including subfolders for each one if tool
contain several files.

If you need to compile something - all should happen under tmp/ subfolder.

If something needed to be installed onto host system - ask for it - operator
will do it or suggest another solution.

Any problem like screenshot needed but cant be obtained - ask before research yourself.

## Project Tools

Preferred way to solve typical tasks (like "build .trd from files" or "unpack files
from .trd") is to create standalone cli python script for it - then put it under
tools/ subfolder so it can be reused later.

Create skills for added tools, but always ask before skillfile creation.

## Main goal

We want to create an UKNC MC0511 OpenIt! game port, buildable into a
runnable .dsk with modern PC-based software, and comfortable to develop
further (all resources editable as text/asm source).
