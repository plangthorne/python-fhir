from setuptools import setup, find_packages

setup(
    name='pyfhir',
    version='0.0.1',
    package_dir={'': 'src'},
    packages=find_packages('src'),
    namespace_packages=['fhir'],
    include_package_data=True,
    install_requires=[
        'pyjwt>=1.5.3,<2',
        'pyyaml>=3.12,<4',
        'requests>=2.18,<3',
    ],
)
