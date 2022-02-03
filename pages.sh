#!/bin/bash 

export GITHUB_WORKSPACE=/github/workspace
export INPUT_TOKEN=$(cat token.txt)
export GITHUB_REPOSITORY='ramSeraph/opendata'
export INPUT_BUILD_REVISION=""
export INPUT_SOURCE='./docs'
export INPUT_DESTINATION='./docs/_site'
export INPUT_VERBOSE='true'

docker run --platform linux/amd64 --name buildpages --workdir /github/workspace --rm \
	-e INPUT_SOURCE -e INPUT_DESTINATION -e INPUT_FUTURE -e INPUT_BUILD_REVISION -e INPUT_VERBOSE -e INPUT_TOKEN \
	-e GITHUB_WORKSPACE -e GITHUB_REPOSITORY -e CI=true -v "$PWD":"/github/workspace" ghcr.io/actions/jekyll-build-pages:latest
