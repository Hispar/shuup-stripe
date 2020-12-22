# -*- coding: utf-8 -*-
# This file is part of Shuup Stripe Addon.
#
# Copyright (c) 2012-2018, Shoop Commerce Ltd. All rights reserved.
#
# This source code is licensed under the OSL-3.0 license found in the
# LICENSE file in the root directory of this source tree.
from django import forms
from django.utils.translation import ugettext_lazy as _


class StripeTokenForm(forms.Form):
    # We're using camel case here only because that's what Stripe does
    stripeToken = forms.CharField(widget=forms.HiddenInput, required=False)
    stripeTokenType = forms.CharField(widget=forms.HiddenInput, required=False)
    stripeEmail = forms.CharField(widget=forms.HiddenInput, required=False)
    stripeCustomer = forms.CharField(widget=forms.HiddenInput, required=False)

    def clean(self):
        data = super(StripeTokenForm, self).clean()
        if not (data.get("stripeToken") or data.get("stripeCustomer")):
            raise forms.ValidationError(_("Either token or customer should be informed."))

        return data
