# -*- coding: utf-8 -*-
# This file is part of Shuup Stripe Addon.
#
# Copyright (c) 2012-2018, Shoop Commerce Ltd. All rights reserved.
#
# This source code is licensed under the OSL-3.0 license found in the
# LICENSE file in the root directory of this source tree.
from logging import getLogger

import stripe
from django.utils.encoding import force_text
from django.utils.translation import ugettext as _
from django.views.generic.edit import FormView
from shuup.front.checkout import (
    BasicServiceCheckoutPhaseProvider, CheckoutPhaseViewMixin
)
from shuup.utils.excs import Problem

from shuup_stripe.models import StripeCustomer

from .checkout_forms import StripeTokenForm, StripePaymentIntentForm
from .models import StripeCheckoutPaymentProcessor
from .utils import get_amount_info, get_checkout_phase_title

LOGGER = getLogger(__name__)


class StripeCheckoutPhase(CheckoutPhaseViewMixin, FormView):
    service = None  # Injected by the method phase
    identifier = "stripe"
    template_name = "shuup/stripe/checkout_phase.jinja"
    form_class = StripePaymentIntentForm

    @property
    def title(self):
        return get_checkout_phase_title(self.request.shop) or "Stripe"

    def get_stripe_context(self):
        payment_processor = self.service.payment_processor
        publishable_key = payment_processor.publishable_key
        secret_key = payment_processor.secret_key
        if not (publishable_key and secret_key):
            raise Problem(
                _("Please configure Stripe keys for payment processor %s.") %
                payment_processor)

        config = {
            "publishable_key": publishable_key,
            "name": force_text(self.request.shop),
            "description": force_text(_("Purchase")),
        }
        config.update(get_amount_info(self.request.basket.taxful_total_price))
        return config

    def get_context_data(self, **kwargs):
        context = super(StripeCheckoutPhase, self).get_context_data(**kwargs)
        context["stripe"] = self.get_stripe_context()
        context["customer"] = self.request.customer

        if self.request.customer:
            stripe_customer = StripeCustomer.objects.filter(contact=self.request.customer).first()
            payment_processor = self.service.payment_processor

            if stripe_customer:
                import stripe
                stripe.api_key = payment_processor.secret_key

                try:
                    customer = stripe.Customer.retrieve(stripe_customer.customer_token)
                    context["stripe_customer_data"] = customer.to_dict()
                except stripe.error.StripeError:
                    LOGGER.exception("Failed to fetch Stripe customer")

        return context

    def is_valid(self):
        return "paymentIntentId" in self.storage.get("stripe", {})

    def form_valid(self, form):
        self.storage["stripe"] = {
            "paymentIntentId": form.cleaned_data.get("paymentIntentId"),
            # "token_type": form.cleaned_data.get("stripeTokenType"),
            # "email": form.cleaned_data.get("stripeEmail"),
            # "customer": form.cleaned_data.get("stripeCustomer")
        }
        return super(StripeCheckoutPhase, self).form_valid(form)

    def process(self):
        self.request.basket.payment_data["stripe"] = self.storage["stripe"]


class StripeCheckoutPhaseProvider(BasicServiceCheckoutPhaseProvider):
    phase_class = StripeCheckoutPhase
    service_provider_class = StripeCheckoutPaymentProcessor
