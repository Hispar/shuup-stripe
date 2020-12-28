# -*- coding: utf-8 -*-
# This file is part of Shuup Stripe Addon.
#
# Copyright (c) 2012-2018, Shoop Commerce Ltd. All rights reserved.
#
# This source code is licensed under the OSL-3.0 license found in the
# LICENSE file in the root directory of this source tree.
import json
from logging import getLogger

import stripe
from django.contrib import messages
from django.http import Http404
from django.http.response import HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.encoding import force_text
from django.utils.translation import ugettext_lazy as _
from django.views.generic import DetailView, TemplateView
from django.views.generic.base import View
from shuup.core.models import get_person_contact, Order
from shuup.front.views.dashboard import DashboardViewMixin
from shuup.utils.excs import Problem

from shuup_stripe.checkout_forms import StripeTokenForm
from shuup_stripe.models import StripeCheckoutPaymentProcessor, StripeCustomer
from shuup_stripe.utils import get_amount_info, get_stripe_processor

LOGGER = getLogger(__name__)


class StripeSavedPaymentInfoView(DashboardViewMixin, TemplateView):
    template_name = "shuup/stripe/saved_payment_info.jinja"

    def post(self, request, *args, **kwargs):
        stripe_processor = get_stripe_processor(request)
        stripe_token = request.POST.get("stripeToken")
        stripe_customer = None

        if stripe_token:
            person_contact = get_person_contact(self.request.user)
            stripe.api_key = stripe_processor.secret_key
            stripe_customer = StripeCustomer.objects.filter(contact=person_contact).first()

            try:
                if stripe_customer:
                    stripe.Customer.modify(stripe_customer.customer_token, source=stripe_token)
                else:
                    customer = stripe.Customer.create(source=stripe_token, email=person_contact.email)
                    stripe_customer = StripeCustomer.objects.create(
                        contact=person_contact,
                        customer_token=customer.id
                    )

            except stripe.error.StripeError:
                LOGGER.exception("Failed to create Stripe Customer")
                stripe_customer = None

        if stripe_customer:
            messages.success(request, _("Payment details successfully saved."))
        else:
            messages.error(request, _("Error while saving payment details."))

        return HttpResponseRedirect(reverse("shuup:stripe_saved_payment"))

    def get_context_data(self, **kwargs):
        context = super(StripeSavedPaymentInfoView, self).get_context_data(**kwargs)
        person_contact = get_person_contact(self.request.user)
        stripe_processor = get_stripe_processor(self.request)
        stripe_customer = StripeCustomer.objects.filter(contact=person_contact).first()

        context["stripe_customer"] = stripe_customer
        context["customer"] = person_contact
        context["stripe_processor"] = stripe_processor

        if stripe_customer:
            stripe.api_key = stripe_processor.secret_key

            try:
                customer = stripe.Customer.retrieve(stripe_customer.customer_token)
                context["stripe_customer_data"] = customer.to_dict()
            except stripe.error.StripeError:
                pass

        return context


class StripeCreatePaymentIntentView(DashboardViewMixin, TemplateView):
    def post(self, request, *args, **kwargs):
        stripe_processor = get_stripe_processor(request)
        try:
            stripe.api_key = stripe_processor.secret_key
            data = json.loads(request.body)
            if 'paymentMethodId' in data:
                # Create new PaymentIntent with a PaymentMethod ID from the client.
                intent = stripe.PaymentIntent.create(
                    **get_amount_info(self.request.basket.taxful_total_price),
                    payment_method=data['paymentMethodId'],
                    confirmation_method='manual',
                    capture_method='manual',
                    confirm=True,
                    # If a mobile client passes `useStripeSdk`, set `use_stripe_sdk=true`
                    # to take advantage of new authentication features in mobile SDKs.
                    use_stripe_sdk=True if 'useStripeSdk' in data and data['useStripeSdk'] else None,
                )
                # After create, if the PaymentIntent's status is succeeded, fulfill the order.
            elif 'paymentIntentId' in data:
                # Confirm the PaymentIntent to finalize payment after handling a required action
                # on the client.
                intent = stripe.PaymentIntent.confirm(data['paymentIntentId'])
                # After confirm, if the PaymentIntent's status is succeeded, fulfill the order.

            return self.generate_response(intent)
        except stripe.error.CardError as e:
            return JsonResponse(data={'error': str(e.user_message)})

    def generate_response(self, intent):
        status = intent['status']
        if status == 'requires_action' or status == 'requires_source_action':
            # Card requires authentication
            return JsonResponse(
                {'requiresAction': True, 'paymentIntentId': intent['id'], 'clientSecret': intent['client_secret']})
        elif status == 'requires_payment_method' or status == 'requires_source':
            # Card was not properly authenticated, suggest a new payment method
            return JsonResponse(data={'error': 'Your card was denied, please provide a new payment method'})
        elif status == 'succeeded':
            # Payment is complete, authentication not required
            # To cancel the payment you will need to issue a Refund (https://stripe.com/docs/api/refunds)
            print("💰 Payment received!")
            return JsonResponse({'clientSecret': intent['client_secret']})
        else:
            print("Payment status", status)
            return JsonResponse({'clientSecret': intent['client_secret']})


class StripeDeleteSavedPaymentInfoView(View):
    def post(self, request, *args, **kwargs):
        stripe_processor = get_stripe_processor(request)
        person_contact = get_person_contact(request.user)
        stripe_customer = StripeCustomer.objects.filter(contact=person_contact).first()
        source_id = request.POST.get("source_id")

        if stripe_customer and source_id:
            stripe.api_key = stripe_processor.secret_key

            try:
                customer = stripe.Customer.retrieve(stripe_customer.customer_token)
                customer.sources.retrieve(source_id).delete()
            except stripe.error.StripeError:
                LOGGER.exception("Failed to delete Stripe source")
                messages.error(request, _("Unknown error while removing payment details."))

            else:
                messages.success(request, _("Payment successfully removed."))

        return HttpResponseRedirect(reverse("shuup:stripe_saved_payment"))


class StripePaymentView(DetailView):
    model = Order
    context_object_name = "order"
    template_name = "shuup/stripe/create_payment.jinja"

    def get_object(self, queryset=None):
        return get_object_or_404(self.model, pk=self.kwargs["pk"], key=self.kwargs["key"])

    def dispatch(self, request, *args, **kwargs):
        order = self.object = self.get_object()
        if order.is_paid():
            raise Http404("Order already fully paid.")

        proseccor = order.payment_method.payment_processor
        if not isinstance(proseccor, StripeCheckoutPaymentProcessor):
            raise Http404("Stripe not selected payment method.")

        return super(StripePaymentView, self).dispatch(request, args, kwargs)

    def post(self, request, *args, **kwargs):
        order = self.get_object()
        form = StripeTokenForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            payment_data = order.payment_data
            payment_data["stripe"] = {
                "token": data.get("stripeToken"),
                "token_type": data.get("stripeTokenType"),
                "email": data.get("stripeEmail"),
                "customer": data.get("stripeCustomer")
            }
            order.payment_data = payment_data
            order.save(update_fields=["payment_data"])
            return redirect("shuup:order_process_payment", pk=order.pk, key=order.key)

        messages.error(request, _("Error in the payment data. Please re-submit the payment."))
        return super(StripePaymentView, self).get(request, args, kwargs)

    def get_stripe_context(self):
        order = self.get_object()
        payment_processor = order.payment_method.payment_processor
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
        config.update(get_amount_info(order.taxful_total_price))
        return config

    def get_context_data(self, **kwargs):
        context = super(StripePaymentView, self).get_context_data()
        context["stripe"] = self.get_stripe_context()
        context["customer"] = self.request.customer

        if self.request.customer:
            order = self.get_object()
            stripe_customer = StripeCustomer.objects.filter(contact=self.request.customer).first()
            payment_processor = order.payment_method.payment_processor

            if stripe_customer:
                import stripe
                stripe.api_key = payment_processor.secret_key

                try:
                    customer = stripe.Customer.retrieve(stripe_customer.customer_token)
                    context["stripe_customer_data"] = customer.to_dict()
                except stripe.error.StripeError:
                    LOGGER.exception("Failed to fetch Stripe customer")

        return context
