install:
	python -m "distutils2.run" install||python setup.py install

publish:
	python -m "distutils2.run" register sdist upload
