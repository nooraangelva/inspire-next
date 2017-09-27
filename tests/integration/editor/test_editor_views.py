# -*- coding: utf-8 -*-
#
# This file is part of INSPIRE.
# Copyright (C) 2014-2017 CERN.
#
# INSPIRE is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# INSPIRE is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with INSPIRE. If not, see <http://www.gnu.org/licenses/>.
#
# In applying this license, CERN does not waive the privileges and immunities
# granted to it by virtue of its status as an Intergovernmental Organization
# or submit itself to any jurisdiction.

from __future__ import absolute_import, division, print_function

import os
import json

import pkg_resources
import pytest
import requests_mock

from mock import patch

from invenio_accounts.models import SessionActivity
from invenio_accounts.testutils import login_user_via_session
from invenio_db import db

from inspire_schemas.api import load_schema, validate
from inspire_utils.record import get_value


@pytest.fixture(scope='function')
def log_in_as_cataloger(api_client):
    """Ensure that we're logged in as a privileged user."""
    login_user_via_session(api_client, email='cataloger@inspirehep.net')

    yield

    SessionActivity.query.delete()
    db.session.commit()


@pytest.fixture(scope='function')
def log_in_as_scientist(api_client):
    """Ensure that we're logged in as an unprivileged user."""
    login_user_via_session(api_client, email='johndoe@inspirehep.net')

    yield

    SessionActivity.query.delete()
    db.session.commit()


@patch('inspirehep.modules.editor.views.tickets')
def test_create_rt_ticket(mock_tickets, log_in_as_cataloger, api_client):
    mock_tickets.create_ticket.return_value = 1

    response = api_client.post(
        '/editor/literature/1497201/rt/tickets/create',
        content_type='application/json',
        data=json.dumps({
            'description': 'description',
            'owner': 'owner',
            'queue': 'queue',
            'recid': '4328',
            'subject': 'subject',
        }),
    )

    assert response.status_code == 200


@patch('inspirehep.modules.editor.views.tickets')
def test_create_rt_ticket_only_needs_queue_and_recid(mock_tickets, log_in_as_cataloger, api_client):
    mock_tickets.create_ticket.return_value = 1

    response = api_client.post(
        '/editor/literature/1497201/rt/tickets/create',
        content_type='application/json',
        data=json.dumps({
            'queue': 'queue',
            'recid': '4328',
        }),
    )

    assert response.status_code == 200


@patch('inspirehep.modules.editor.views.tickets')
def test_create_rt_ticket_returns_500_on_error(mock_tickets, log_in_as_cataloger, api_client):
    mock_tickets.create_ticket.return_value = -1

    response = api_client.post(
        '/editor/literature/1497201/rt/tickets/create',
        content_type='application/json',
        data=json.dumps({
            'description': 'description',
            'owner': 'owner',
            'queue': 'queue',
            'recid': '4328',
            'subject': 'subject',
        }),
    )

    assert response.status_code == 500

    expected = {'success': False}
    result = json.loads(response.data)

    assert expected == result


def test_create_rt_ticket_returns_403_on_authentication_error(api_client):
    response = api_client.post('/editor/literature/1497201/rt/tickets/create')

    assert response.status_code == 403


@patch('inspirehep.modules.editor.views.tickets')
def test_resolve_rt_ticket(mock_tickets, log_in_as_cataloger, api_client):
    response = api_client.get('/editor/literature/1497201/rt/tickets/4328/resolve')

    assert response.status_code == 200

    expected = {'success': True}
    result = json.loads(response.data)

    assert expected == result


def test_resolve_rt_ticket_returns_403_on_authentication_error(api_client):
    response = api_client.get('/editor/literature/1497201/rt/tickets/4328/resolve')

    assert response.status_code == 403


@patch('inspirehep.modules.editor.views.tickets')
def test_get_tickets_for_record(mock_tickets, log_in_as_cataloger, api_client):
    response = api_client.get('/editor/literature/1497201/rt/tickets')

    assert response.status_code == 200


def test_get_tickets_for_record_returns_403_on_authentication_error(api_client):
    response = api_client.get('/editor/literature/1497201/rt/tickets')

    assert response.status_code == 403


@patch('inspirehep.modules.editor.views.tickets')
def test_get_rt_users(mock_tickets, log_in_as_cataloger, api_client):
    response = api_client.get('/editor/literature/1497201/rt/users')

    assert response.status_code == 200


def test_get_rt_users_returns_403_on_authentication_error(api_client):
    response = api_client.get('/editor/literature/1497201/rt/users')

    assert response.status_code == 403


@patch('inspirehep.modules.editor.views.tickets')
def test_get_rt_queues(mock_tickets, log_in_as_cataloger, api_client):
    response = api_client.get('/editor/literature/1497201/rt/queues')

    assert response.status_code == 200


def test_get_rt_queues_returns_403_on_authentication_error(log_in_as_scientist, api_client):
    response = api_client.get('/editor/literature/1497201/rt/queues')

    assert response.status_code == 403


def test_check_permission_success(log_in_as_cataloger, api_client):
    response = api_client.get('/editor/literature/1497201/permission')

    assert response.status_code == 200


def test_check_permission_returns_403_on_authentication_error(log_in_as_scientist, api_client):
    response = api_client.get('/editor/literature/1497201/permission')

    assert response.status_code == 403


def test_editor_permission_is_cached(log_in_as_cataloger, api_client):
    cache_key = 'editor-permission-literature-1497201'
    with api_client.session_transaction() as sess:
        assert cache_key not in sess

    api_client.get('/editor/literature/1497201/permission')

    with api_client.session_transaction() as sess:
        assert sess[cache_key] is True


def test_authorlist_text(log_in_as_cataloger, api_client):
    schema = load_schema('hep')
    subschema = schema['properties']['authors']

    response = api_client.post(
        '/editor/literature/1497201/authorlist/text',
        content_type='application/json',
        data=json.dumps({
            'text': (
                'F. Lastname1, F.M. Otherlastname1,2\n'
                '\n'
                '1 CERN\n'
                '2 Otheraffiliation'
            )
        })
    )

    assert response.status_code == 200

    expected = {
        'authors': [
            {
                'full_name': 'Lastname, F.',
                'raw_affiliations': [
                    {'value': 'CERN'},
                ],
            },
            {
                'full_name': 'Otherlastname, F.M.',
                'raw_affiliations': [
                    {'value': 'CERN'},
                    {'value': 'Otheraffiliation'},
                ],
            },
        ],
    }
    result = json.loads(response.data)

    assert validate(result['authors'], subschema) is None
    assert expected == result


def test_authorlist_text_exception(log_in_as_cataloger, api_client):
    response = api_client.post(
        '/editor/literature/1497201/authorlist/text',
        content_type='application/json',
        data=json.dumps({
            'text': 'A. Einstein, N. Bohr2'
        })
    )

    assert response.status_code == 500

    expected = {
        'message': 'Could not find affiliations',
        'status': 500
    }
    result = json.loads(response.data)

    assert expected == result


def test_refextract_text(log_in_as_cataloger, api_client):
    schema = load_schema('hep')
    subschema = schema['properties']['references']

    response = api_client.post(
        '/editor/literature/1497201/refextract/text',
        content_type='application/json',
        data=json.dumps({
            'text': (
                u'J. M. Maldacena. “The Large N Limit of Superconformal Field '
                u'Theories and Supergravity”. Adv. Theor. Math. Phys. 2 (1998), '
                u'pp. 231–252.'
            ),
        }),
    )
    references = json.loads(response.data)

    assert response.status_code == 200
    assert validate(references, subschema) is None
    assert get_value({'references': references}, 'references.reference.publication_info.journal_title')


def test_refextract_url(log_in_as_cataloger, api_client):
    schema = load_schema('hep')
    subschema = schema['properties']['references']

    with requests_mock.Mocker() as requests_mocker:
        requests_mocker.register_uri(
            'GET', 'https://arxiv.org/pdf/1612.06414.pdf',
            content=pkg_resources.resource_string(
                __name__, os.path.join('fixtures', '1612.06414.pdf')),
        )

        response = api_client.post(
            '/editor/literature/1497201/refextract/url',
            content_type='application/json',
            data=json.dumps({
                'url': 'https://arxiv.org/pdf/1612.06414.pdf',
            }),
        )
        references = json.loads(response.data)

    assert response.status_code == 200
    assert validate(references, subschema) is None
    assert get_value({'references': references}, 'references.reference.publication_info.journal_title')
