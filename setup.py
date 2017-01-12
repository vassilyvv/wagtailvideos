#!/usr/bin/env python
"""
Install wagtailvideos using setuptools
"""

with open('README.rst', 'r') as f:
    readme = f.read()

from setuptools import find_packages, setup

setup(
    name='wagtailvideos',
    version='0.3.0',
    description="A wagtail module for uploading and displaying videos in various codecs.",
    long_description=readme,
    author='Takeflight',
    author_email='developers@takeflight.com.au',
    url='https://github.com/takeflight/wagtailvideos',

    install_requires=[
        'wagtail>=1.7',
        'Django>=1.9',
        'django-enumchoicefield==0.6.0',
    ],
    extras_require={
        'testing': [
            'mock==2.0.0'
        ]
    },
    zip_safe=False,
    license='BSD License',

    packages=find_packages(),

    include_package_data=True,
    package_data={},



    classifiers=[
        'Environment :: Web Environment',
        'Intended Audience :: Developers',
        'Operating System :: OS Independent',
        'Programming Language :: Python',
        'Programming Language :: Python :: 2',
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.4',
        'Programming Language :: Python :: 3.5',
        'Framework :: Django',
        'License :: OSI Approved :: BSD License',
    ],
)
