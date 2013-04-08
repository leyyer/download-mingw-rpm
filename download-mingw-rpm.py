#!/usr/bin/env python
#
# Copyright (C) Maarten Bosmans 2011-2012, Renyi su 2013
#
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.
#
from __future__ import with_statement
from urllib import urlretrieve
from io import open
from urllib2 import urlopen
from logging import warning, error
import logging
import os.path
import sys

_packages = []

_scriptDirectory = os.path.dirname(os.path.realpath(__file__))
_packageCacheDirectory = os.path.join(_scriptDirectory, u'cache', u'package')
_repositoryCacheDirectory = os.path.join(_scriptDirectory, u'cache', u'repository')
_extractedCacheDirectory = os.path.join(_scriptDirectory, u'cache', u'extracted')
_extractedFilesDirectory = _scriptDirectory


def OpenRepository(repositoryLocation, arch=u'noarch'):
  from xml.etree.cElementTree import parse as xmlparse
  global _packages
  # Check repository for latest primary.xml
  myurl = repositoryLocation + u'repodata/repomd.xml'
  metadata = urlopen(myurl)
  doctree = xmlparse(metadata)
  xmlns = u'http://linux.duke.edu/metadata/repo'
  for element in doctree.findall(u'{%s}data'%xmlns):
    if element.get(u'type') == u'primary':
      primaryUrl = element.find(u'{%s}location'%xmlns).get(u'href')
  # Make sure all the cache directories exist
  for dir in _packageCacheDirectory, _repositoryCacheDirectory, _extractedCacheDirectory:
    try:
      os.makedirs(dir)
    except OSError: pass
  # Download repository metadata (only if not already in cache)
  primaryFilename = os.path.join(_repositoryCacheDirectory, os.path.splitext(os.path.basename(primaryUrl))[0])
  if not os.path.exists(primaryFilename):
	warning(u'Dowloading repository data')
	mypriurl = repositoryLocation + primaryUrl
	primaryGzFile = urlopen(mypriurl)
	if primaryGzFile:
		import io, gzip
		primaryGzString = io.BytesIO(primaryGzFile.read()) #3.2: use gzip.decompress
		with gzip.GzipFile(fileobj=primaryGzString) as primaryGzipFile:
			with open(primaryFilename, u'wb') as primaryFile:
				primaryFile.writelines(primaryGzipFile)
  elements = xmlparse(primaryFilename)
  # Parse package list from XML
  xmlns = u'http://linux.duke.edu/metadata/common'
  rpmns = u'http://linux.duke.edu/metadata/rpm'
  _packages = [{
      u'name': p.find(u'{%s}name'%xmlns).text,
      u'buildtime': int(p.find(u'{%s}time'%xmlns).get(u'build')),
      u'url': repositoryLocation + p.find(u'{%s}location'%xmlns).get(u'href'),
      u'filename': os.path.basename(p.find(u'{%s}location'%xmlns).get(u'href')),
      u'provides': set(provides.attrib[u'name'] for provides in p.findall(u'{%s}format/{%s}provides/{%s}entry'%(xmlns,rpmns,rpmns))),
      u'requires': set(req.attrib[u'name'] for req in p.findall(u'{%s}format/{%s}requires/{%s}entry'%(xmlns,rpmns,rpmns)))
    } for p in elements.findall(u'{%s}package'%xmlns) if p.find(u'{%s}arch'%xmlns).text == arch]


def _findPackage(packageName):
  sort_func = lambda p: p[u'buildtime']
  packages = sorted([p for p in _packages if packageName in [p[u'name'], p[u'filename']]], key=sort_func, reverse=True)
  if len(packages) == 0:
    return None
  if len(packages) > 1:
    error(u'multiple packages found for %s:', packageName)
    for p in packages:
      error(u'  %s', p[u'filename'])
  return packages[0]


def _checkPackageRequirements(package, packageNames):
  allProviders = set()
  for requirement in package[u'requires']:
    providers = set(p[u'name'] for p in _packages if requirement in p[u'provides'])
    if not (providers & packageNames):
      if providers:
        warning(u'Package %s requires %s, provided by: %s', package[u'name'], requirement, u','.join(providers))
        allProviders.add(providers.pop())
      else:
        error(u'Package %s requires %s, not provided by any package', package[u'name'], requirement)
  return allProviders


def packagesDownload(packageNames, withDependencies=False):
  from fnmatch import fnmatchcase
  packageNames_new = set(pn for pn in packageNames if pn.endswith(u'.rpm'))
  for packageName in packageNames - packageNames_new:
    matchedpackages = set(p[u'name'] for p in _packages if fnmatchcase(p[u'name'].replace(u'mingw32-', u'').replace(u'mingw64-', u''), packageName))
    packageNames_new |= matchedpackages or set([packageName])
  packageNames = list(packageNames_new)
  allPackageNames = set(packageNames)

  packageFilenames = []
  while packageNames:
    packName = packageNames.pop()
    package = _findPackage(packName)
    if package == None:
      error(u'Package %s not found', packName)
      continue
    dependencies = _checkPackageRequirements(package, allPackageNames)
    if withDependencies and dependencies:
      packageNames.extend(dependencies)
      allPackageNames |= dependencies
    localFilenameFull = os.path.join(_packageCacheDirectory, package[u'filename'])
    if not os.path.exists(localFilenameFull):
      warning(u'Downloading %s', package[u'filename'])
      urlretrieve(package[u'url'], localFilenameFull)
    packageFilenames.append(package[u'filename'])
  return packageFilenames


def _extractFile(filename, output_dir=_extractedCacheDirectory):
  from subprocess import check_call
  try:
    with open(u'7z.log', u'w') as logfile:
      check_call([u'7z', u'x', u'-o'+output_dir, u'-y', filename], stdout=logfile)
    os.remove(u'7z.log')
  except:
    error(u'Failed to extract %s', filename)


def packagesExtract(packageFilenames, srcpkg=False):
  for packageFilename in packageFilenames :
    warning(u'Extracting %s', packageFilename)
    cpioFilename = os.path.join(_extractedCacheDirectory, os.path.splitext(packageFilename)[0] + u'.cpio')
    if not os.path.exists(cpioFilename):
      _extractFile(os.path.join(_packageCacheDirectory, packageFilename))
    if srcpkg:
      _extractFile(cpioFilename, os.path.join(_extractedFilesDirectory, os.path.splitext(packageFilename)[0]))
    else:
      _extractFile(cpioFilename, _extractedFilesDirectory)


def GetBaseDirectory():
  if os.path.exists(os.path.join(_extractedFilesDirectory, u'usr/i686-w64-mingw32/sys-root/mingw')):
    return os.path.join(_extractedFilesDirectory, u'usr/i686-w64-mingw32/sys-root/mingw')
  if os.path.exists(os.path.join(_extractedFilesDirectory, u'usr/x86_64-w64-mingw32/sys-root/mingw')):
    return os.path.join(_extractedFilesDirectory, u'usr/x86_64-w64-mingw32/sys-root/mingw')
  return _extractedFilesDirectory


def CleanExtracted():
  from shutil import rmtree
  rmtree(os.path.join(_extractedFilesDirectory, u'usr'), True)


def SetExecutableBit():
  # set executable bit on libraries and executables
  for root, dirs, files in os.walk(GetBaseDirectory()):
    for filename in set(f for f in files if f.endswith(u'.dll') or f.endswith(u'.exe')) | set(dirs):
      os.chmod(os.path.join(root, filename), 0755)


def GetOptions():
  from optparse import OptionParser, OptionGroup #3.2: use argparse

  parser = OptionParser(usage=u"usage: %prog [options] packages",
                        description=u"Easy download of RPM packages for Windows.")

  # Options specifiying download repository
  default_project = u"windows:mingw:win32"
  default_repository = u"openSUSE_Factory"
  default_repo_url = u"http://download.opensuse.org/repositories/PROJECT/REPOSITORY/"
  repoOptions = OptionGroup(parser, u"Specify download repository")
  repoOptions.add_option(u"-p", u"--project", dest=u"project", default=default_project,
                         metavar=u"PROJECT", help=u"Download from PROJECT [%default]")
  repoOptions.add_option(u"-r", u"--repository", dest=u"repository", default=default_repository,
                         metavar=u"REPOSITORY", help=u"Download from REPOSITORY [%default]")
  repoOptions.add_option(u"-u", u"--repo-url", dest=u"repo_url", default=default_repo_url,
                         metavar=u"URL", help=u"Download packages from URL (overrides PROJECT and REPOSITORY options) [%default]")
  parser.add_option_group(repoOptions)

  # Package selection options
  parser.set_defaults(withdeps=False)
  packageOptions = OptionGroup(parser, u"Package selection")
  packageOptions.add_option(u"--deps", action=u"store_true", dest=u"withdeps", help=u"Download dependencies")
  packageOptions.add_option(u"--no-deps", action=u"store_false", dest=u"withdeps", help=u"Do not download dependencies [default]")
  packageOptions.add_option(u"--src", action=u"store_true", dest=u"srcpkg", default=False, help=u"Download source instead of noarch package")
  parser.add_option_group(packageOptions)

  # Output options
  outputOptions = OptionGroup(parser, u"Output options", u"Normally the downloaded packages are extracted in the current directory.")
  outputOptions.add_option(u"--no-clean", action=u"store_false", dest=u"clean", default=True,
                           help=u"Do not remove previously extracted files")
  outputOptions.add_option(u"-z", u"--make-zip", action=u"store_true", dest=u"makezip", default=False,
                           help=u"Make a zip file of the extracted packages (the name of the zip file is based on the first package specified)")
  outputOptions.add_option(u"-m", u"--add-metadata", action=u"store_true", dest=u"metadata", default=False,
                           help=u"Add a file containing package dependencies and provides")
  parser.add_option_group(outputOptions)

  # Other options
  parser.add_option(u"-q", u"--quiet", action=u"store_false", dest=u"verbose", default=True,
                    help=u"Don't print status messages to stderr")

  (options, args) = parser.parse_args()

  if len(args) == 0:
    parser.print_help(file=sys.stderr)
    sys.exit(1)

  return (options, args)


def main():
  import re, zipfile 

  (options, args) = GetOptions()
  packages = set(args)
  logging.basicConfig(level=(logging.WARNING if options.verbose else logging.ERROR), format=u'%(message)s', stream=sys.stderr)

  # Open repository
  repository = options.repo_url.replace(u"PROJECT", options.project.replace(u':', u':/')).replace(u"REPOSITORY", options.repository)
  try:
    OpenRepository(repository, u'src' if options.srcpkg else u'noarch')
  except Exception, e:
    sys.exit(u'Error opening repository:\n\t%s\n\t%s' % (repository, e))

  if options.clean:
    CleanExtracted()

  if options.makezip or options.metadata:
    package = _findPackage(args[0]) or _findPackage(u"mingw32-"+args[0]) or _findPackage(u"mingw64-"+args[0])
    if package == None:
      sys.exit(u'Package not found:\n\t%s' % args[0])
    packageBasename = re.sub(u'^mingw(32|64)-|\\.noarch|\\.rpm$', u'', package[u'filename'])

  packages = packagesDownload(packages, options.withdeps)
  for package in sorted(packages):
    print package

  packagesExtract(packages, options.srcpkg)
  SetExecutableBit()

  if options.metadata:
    cleanup = lambda n: re.sub(u'^mingw(?:32|64)-(.*)', u'\\1', re.sub(u'^mingw(?:32|64)[(](.*)[)]', u'\\1', n))
    with open(os.path.join(GetBaseDirectory(), packageBasename + u'.metadata'), u'w') as m:
      for packageFilename in sorted(packages):
        package = [p for p in _packages if p[u'filename'] == packageFilename][0]
        m.writelines([u'provides:%s\r\n' % cleanup(p) for p in package[u'provides']])
        m.writelines([u'requires:%s\r\n' % cleanup(r) for r in package[u'requires']])

  if options.makezip:
    packagezip = zipfile.ZipFile(packageBasename + u'.zip', u'w', compression=zipfile.ZIP_DEFLATED)
    for root, dirs, files in os.walk(GetBaseDirectory()):
      for filename in files:
        fullname = os.path.join(root, filename)
        packagezip.write(fullname, fullname.replace(GetBaseDirectory(), u''))
    packagezip.close() #3.2: use with
    if options.clean:
      CleanExtracted()

if __name__ == u"__main__":
    main()

