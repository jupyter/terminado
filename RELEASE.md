This repository uses [`jupyter_releaser`](https://github.com/jupyter-server/jupyter_releaser) for automated releases.

To create a manual release, update the version number in `terminado/__init__.py`, then run the following:

```
git clean -dffx
pip install pipx
pipx run build
export script_version=`pipx run hatch version 2>/dev/null`
git commit -a -m "Release $script_version"
git tag $script_version
git push --all
git push --tags
pipx run twine check dist/*
pipx run twine upload dist/*
```
