# -*- coding: utf-8 -*-
# This file is part of Shuup Stripe Addon.
#
# Copyright (c) 2012-2018, Shoop Commerce Ltd. All rights reserved.
#
# This source code is licensed under the OSL-3.0 license found in the
# LICENSE file in the root directory of this source tree.
import stripe
from django.utils.translation import ugettext as _
from shuup.utils.excs import Problem

from shuup_stripe.utils import get_amount_info


def _handle_stripe_error(charge_data):
    error_dict = charge_data.get("error")
    if error_dict:
        raise Problem("Stripe: %(message)s (%(type)s)" % error_dict)
    failure_code = charge_data.get("failure_code")
    failure_message = charge_data.get("failure_message")
    if failure_code or failure_message:
        raise Problem(
            _("Stripe: %(failure_message)s (%(failure_code)s)") % charge_data
        )


class StripeCharger(object):
    identifier = "stripe"
    name = _("Stripe Checkout")

    def __init__(self, secret_key, order):
        self.secret_key = secret_key
        self.order = order

    def _fetch_source(self):
        stripe_token = self.order.payment_data["stripe"].get("token")
        input_data = {}
        if stripe_token:
            input_data["token"] = stripe_token

        stripe.api_key = self.secret_key
        return stripe.Source.create(**input_data)

    def _send_request(self):
        stripe_source = self._fetch_source()
        stripe_customer = self.order.payment_data["stripe"].get("customer")
        input_data = {
            "description": _("Payment for order {id} on {shop}").format(
                id=self.order.identifier, shop=self.order.shop,
            )
        }
        if stripe_source:
            input_data["source"] = stripe_source["id"]
        elif stripe_customer:
            input_data["customer"] = stripe_customer

        input_data.update(get_amount_info(self.order.taxful_total_price))

        stripe.api_key = self.secret_key
        return stripe.PaymentIntent.create(
            **input_data,
            payment_method_types=["card"],
        )

    def create_payment_intent(self):
        resp = self._send_request()
        payment_intent_data = resp.json() if hasattr(resp, "json") else resp
        _handle_stripe_error(payment_intent_data)
        status = payment_intent_data.get("status", False)
        if not status or 'status' != 'succeeded':
            raise Problem(_("Stripe status is not 'succeeded'"))

        return self.order.create_payment(
            self.order.taxful_total_price,
            payment_identifier="Stripe-%s" % payment_intent_data["id"],
            description=_("Stripe Payment Intent")
        )
