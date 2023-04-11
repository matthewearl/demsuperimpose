# Quake demo superimposer

Tool for adding "ghosts" into a demo.  Takes a base demo, and adds the view
entity from a list of other demos.  Useful for showing many speedrun attempts in
a single demo.  For best results try recamming the result.

## Usage

Clone [kugelrund's pydem repo](https://github.com/kugelrund/pydem) and this
repo:

```bash
git clone git@github.com:kugelrund/pydem.git
git clone git@github.com:matthewearl/demsuperimpose.git
```

Run the following to convert a demo:

```bash
PYTHONPATH=pydem python demsuperimpose/demsuperimpose.py base.dem ghost1.dem ghost2.dem ...
```

This writes a file `out.dem`.

## Limitations

- All input demos must be single level only, ie. there must be exactly one
  server info command in the demo.
- Ghost skin colors are stuck at the default.  It should be possible to fix this
  by inserting `svc_updatecolors` commands, but only up to 16 total players,
  since that is Quake's hardcoded maximum scoreboard size.
