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

"""Contains INSPIRE specific submission tasks."""

from __future__ import absolute_import, division, print_function

import os
import logging
from functools import wraps
from pprint import pformat

import backoff
import rt
from flask import current_app

from invenio_accounts.models import User
from invenio_db import db

from inspire_dojson import record2marcxml

from inspirehep.modules.workflows.models import WorkflowsPendingRecord
from inspirehep.modules.workflows.tasks.actions import in_production_mode
from inspirehep.modules.workflows.utils import with_debug_logging
from inspirehep.utils.robotupload import make_robotupload_marcxml
from inspirehep.utils import tickets
from inspirehep.utils.proxies import rt_instance


LOGGER = logging.getLogger(__name__)


@with_debug_logging
@backoff.on_exception(backoff.expo, rt.ConnectionError, base=4, max_tries=5)
def submit_rt_ticket(obj,
                     queue,
                     template,
                     context,
                     requestors,
                     recid,
                     ticket_id_key):
    """Submit ticket to RT with the given parameters."""
    new_ticket_id = tickets.create_ticket_with_template(queue,
                                                        requestors,
                                                        template,
                                                        context,
                                                        context.get("subject"),
                                                        recid)
    obj.extra_data[ticket_id_key] = new_ticket_id
    obj.log.info(u'Ticket {0} created'.format(new_ticket_id))
    return new_ticket_id


def create_ticket(template,
                  context_factory=None,
                  queue="Test",
                  ticket_id_key="ticket_id"):
    """Create a ticket.

    Creates the ticket in the given queue and stores the ticket ID
    in the extra_data key specified in ticket_id_key.
    """
    @with_debug_logging
    @wraps(create_ticket)
    def _create_ticket(obj, eng):
        user = User.query.get(obj.id_user)

        context = {}
        if context_factory:
            context = context_factory(user, obj)

        if not in_production_mode():
            obj.log.info(
                u'Was going to create ticket: {subject}\n'
                u'To: {requestors} Queue: {queue}'.format(
                    queue=queue,
                    subject=context.get('subject'),
                    requestors=user.email if user else '',
                )
            )
            return {}

        recid = obj.extra_data.get("recid") or obj.data.get("control_number")

        new_ticket_id = submit_rt_ticket(
            obj,
            queue,
            template,
            context,
            user.email if user else '',
            recid,
            ticket_id_key
        )
        return {ticket_id_key: new_ticket_id}

    return _create_ticket


def reply_ticket(template=None,
                 context_factory=None,
                 keep_new=False):
    """Reply to a ticket for the submission."""
    @with_debug_logging
    @wraps(reply_ticket)
    def _reply_ticket(obj, eng):
        ticket_id_key = "ticket_id"
        ticket_id = obj.extra_data.get(ticket_id_key)

        if not rt_instance:
            obj.log.error("No RT instance available. Skipping!")
            obj.log.info(
                "Was going to reply to {ticket_id}\n".format(
                    ticket_id=ticket_id,
                )
            )
            return {}

        if not ticket_id:
            obj.log.error("No ticket ID found!")
            return {}

        user = User.query.get(obj.id_user)
        if not user:
            obj.log.error(
                "No user found for object %s, skipping ticket creation", obj.id)
            return {}

        if template:
            context = {}
            if context_factory:
                context = context_factory(user, obj)
            tickets.reply_ticket_with_template(ticket_id,
                                               template,
                                               context,
                                               keep_new)
        else:
            # Body already rendered in reason.
            body = obj.extra_data.get("reason", "")
            if body:
                tickets.reply_ticket(ticket_id, body, keep_new)
            else:
                obj.log.error("No body for ticket reply. Skipping reply.")

        return {}

    return _reply_ticket


def close_ticket(ticket_id_key="ticket_id"):
    """Close the ticket associated with this record found in given key."""
    @with_debug_logging
    @wraps(close_ticket)
    def _close_ticket(obj, eng):
        ticket_id = obj.extra_data.get(ticket_id_key, "")
        if not ticket_id:
            obj.log.error("No ticket ID found!")
            return {}

        if not rt_instance:
            obj.log.error("No RT instance available. Skipping!")
            obj.log.info(
                "Was going to close ticket {ticket_id}".format(
                    ticket_id=ticket_id,
                )
            )
            return {}

        tickets.resolve_ticket(ticket_id)
        return {}

    return _close_ticket


def send_robotupload(
    url=None,
    callback_url="callback/workflows/robotupload",
    mode="insert",
    extra_data_key=None,
    priority_config_key=None,
):
    """Get the MARCXML from the model and ship it.

    If callback_url is set the workflow will halt and the callback is
    responsible for resuming it.
    """
    @with_debug_logging
    @wraps(send_robotupload)
    def _send_robotupload(obj, eng):
        if not current_app.config.get('FEATURE_FLAG_ENABLE_SEND_TO_LEGACY', True):
            obj.log.info(
                'skipping upload to legacy, feature flag ``FEATURE_FLAG_ENABLE_SEND_TO_LEGACY`` is disabled.'
            )
            return

        combined_callback_url = ''
        if callback_url:
            combined_callback_url = os.path.join(
                current_app.config["SERVER_NAME"],
                callback_url
            )
            if not combined_callback_url.startswith('http'):
                combined_callback_url = "https://{0}".format(
                    combined_callback_url
                )

        if extra_data_key is not None:
            data = obj.extra_data.get(extra_data_key) or {}
        else:
            data = obj.data

        marcxml = record2marcxml(data)

        if current_app.debug:
            # Log what we are sending
            LOGGER.debug(
                "Going to robotupload mode:%s to url:%s:\n%s\n",
                mode,
                url,
                marcxml,
            )

        if not in_production_mode():
            obj.log.debug(
                "Going to robotupload %s to %s:\n%s\n",
                mode,
                url,
                marcxml,
            )
            obj.log.debug(
                "Base object data:\n%s",
                pformat(data)
            )
            return

        priority = 5
        if priority_config_key:
            priority = current_app.config.get(priority_config_key, priority)

        result = make_robotupload_marcxml(
            url=url,
            marcxml=marcxml,
            callback_url=combined_callback_url,
            mode=mode,
            nonce=obj.id,
            priority=priority,
        )
        if "[INFO]" not in result.text:
            if "cannot use the service" in result.text:
                # IP not in the list
                obj.log.error("Your IP is not in "
                              "app.config_BATCHUPLOADER_WEB_ROBOT_RIGHTS "
                              "on host: %s", result.text)
            txt = "Error while submitting robotupload: {0}".format(result.text)
            raise Exception(txt)
        else:
            obj.log.info("Robotupload sent!")
            obj.log.info(result.text)
            if callback_url:
                eng.halt("Waiting for robotupload: {0}".format(result.text))

        obj.log.info("end of upload")

    return _send_robotupload


@with_debug_logging
def send_to_legacy(priority_config_key=None):
    """Send the record in the workflow to legacy.

    Args:
        priority_config_key (Optional[str]): if present, config key specifiying
            the robotupload the priority to use. If the key does not exist, the
            default priority is used.
    """
    def _send_to_legacy(obj, eng):
        if not current_app.config.get('FEATURE_FLAG_ENABLE_SEND_TO_LEGACY', True):
            obj.log.info(
                'skipping upload to legacy, feature flag ``FEATURE_FLAG_ENABLE_SEND_TO_LEGACY`` is disabled.'
            )
            return

        update_legacy_flag = current_app.config.get('FEATURE_FLAG_ENABLE_UPDATE_TO_LEGACY', False)

        if obj.extra_data.get('is-update', False) and not update_legacy_flag:
            obj.log.info(
                'skipping upload to legacy, feature flag ``FEATURE_FLAG_ENABLE_UPDATE_TO_LEGACY`` is disabled.'
            )
            return

        send_robotupload(mode='replace', priority_config_key=priority_config_key)(obj, eng)

    return _send_to_legacy


@with_debug_logging
def wait_webcoll(obj, eng):
    if not in_production_mode():
        obj.log.debug("Would have wait for webcoll callback.")
        return

    eng.halt("Waiting for webcoll.")


@with_debug_logging
def filter_keywords(obj, eng):
    """Removes non-accepted keywords from the metadata"""
    prediction = obj.extra_data.get('keywords_prediction', {})
    if prediction:
        keywords = prediction.get('keywords')

        keywords = filter(lambda x: x['accept'], keywords)
        obj.extra_data['keywords_prediction']['keywords'] = keywords

        obj.log.debug('Filtered keywords: \n%s', pformat(keywords))

    obj.log.debug('Got no prediction for keywords')


@with_debug_logging
def prepare_keywords(obj, eng):
    """Prepares the keywords in the correct format to be sent"""
    def _check_keyword_should_be_left_untouched(keyword):
        if keyword.get('schema', '') == "INSPIRE" and keyword.get('source') is None:
            return True
        return False

    def _filter_out_classifier_keywords(keyword):
        if keyword.get('schema', '') == "INSPIRE" and keyword.get("source", '') == 'classifier':
            return False
        return True
    keywords = obj.data.get('keywords', [])
    if obj.data.get('core'):
        # if there is any INSPIRE keyword without `source: classifier` then don't do anything.
        untouchable_keywords = any(_check_keyword_should_be_left_untouched(kw) for kw in keywords)
        if untouchable_keywords:
            return
        keywords = [kw for kw in keywords if _filter_out_classifier_keywords(kw)]

        extracted_keywords = obj.extra_data.get('extracted_keywords', [])
        for keyword in extracted_keywords:
            if keyword:
                keywords.append(
                    {
                        "value": keyword,
                        "schema": "INSPIRE",
                        "source": "classifier"
                    }
                )
    if keywords:
        obj.data['keywords'] = keywords

    obj.log.debug('Finally got keywords: \n%s', pformat(keywords))


@with_debug_logging
def cleanup_pending_workflow(obj, eng):
    """Cleans up the pending workflow entry for this workflow if any."""
    WorkflowsPendingRecord.query.filter(
        WorkflowsPendingRecord.workflow_id == obj.id
    ).delete()
    db.session.commit()
