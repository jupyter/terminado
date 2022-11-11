The recommended way to make a release is to use [`jupyter_releaser`](https://jupyter-releaser.readthedocs.io/en/latest/get_started/making_release_from_repo.html).

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
