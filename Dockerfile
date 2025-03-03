# -*- coding: utf-8 -*-
#
# This file is part of INSPIRE.
# Copyright (C) 2019 CERN.
#
# INSPIRE is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# INSPIRE is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with INSPIRE. If not, see <http://www.gnu.org/licenses/>.
#
# In applying this licence, CERN does not waive the privileges and immunities
# granted to it by virtue of its status as an Intergovernmental Organization
# or submit itself to any jurisdiction.


# Modified and simplified version of https://github.com/inspirehep/inspire-docker
# to build an imagine to run in https://github.com/inspirehep/inspirehep

FROM centos:7

RUN yum install -y https://dl.fedoraproject.org/pub/epel/epel-release-latest-7.noarch.rpm && \
    yum update -y && \
    yum install -y \
        ImageMagick \
        transfig \
        file \
        firefox \
        gcc \
        gcc-c++ \
        git \
        kstart \
        libffi-devel \
        libxml2-devel \
        libxslt-devel \
        mailcap \
        make \
        openssl-devel \
        poppler-utils \
        postgresql \
        postgresql-libs \
        postgresql-devel \
        python-pip \
        python-devel \
        python2-xrootd \
        wget \
        Xvfb \
        && \
    yum clean all

ENV NODE_VERSION 6.17.1
RUN mkdir /usr/local/nvm
ENV NVM_DIR /usr/local/nvm

RUN curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.1/install.sh | bash

# install node and npm LTS
RUN source $NVM_DIR/nvm.sh \
    && nvm install $NODE_VERSION \
    && nvm alias default $NODE_VERSION \
    && nvm use default

ENV NODE_PATH $NVM_DIR/v$NODE_VERSION/lib/node_modules
ENV PATH $NVM_DIR/versions/node/v$NODE_VERSION/bin:$PATH

RUN npm install -g \
        node-sass@3.8.0 \
        clean-css@^3.4.24 \
        requirejs \
        uglify-js

ENV PATH="/root/.poetry/bin:${PATH}" \
    POETRY_VIRTUALENVS_CREATE=false \
    POETRY_VERSION=1.1.6

WORKDIR /code

RUN curl -sSL https://raw.githubusercontent.com/python-poetry/poetry/4ec09d4e6b8ca007e67bb873c96277b54986fbdb/get-poetry.py \
    | sed -E 's/(self\._get\(self\.METADATA_URL\).decode)\(\)/\1("utf-8")/' \
    | python && \
    poetry --version && \
    pip install --no-cache-dir --upgrade pip==20.3.4 && \
    pip install --no-cache-dir --upgrade setuptools && \
    pip install --no-cache-dir --upgrade wheel

COPY . .

RUN poetry export --without-hashes -E all -E xrootd -f requirements.txt > requirements.poetry.txt && \
    pip install --ignore-installed --requirement requirements.poetry.txt && \
    pip install -e .

WORKDIR /usr/var/inspirehep-instance/static

RUN inspirehep npm && \
    npm install && \
    inspirehep collect -v && \
    inspirehep assets build

WORKDIR /code
