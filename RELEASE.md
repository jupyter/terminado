This repository uses [`jupyter_releaser`](https://github.com/jupyter-server/jupyter_releaser) for automated releases.

To create a manual release, update the version number in `terminado/__init__.py`, then run the following:

```
git clean -dffx
python setup.py sdist
python setup.py bdist_wheel
export script_version=`python setup.py --version 2>/dev/null`
git commit -a -m "Release $script_version"
git tag $script_version
git push --all
git push --tags
pip install twine
twine check dist/*
twine upload dist/*
```
