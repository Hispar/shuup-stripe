# -*- coding: utf-8 -*-
# This file is part of Shuup Stripe Addon.
#
# Copyright (c) 2012-2018, Shoop Commerce Ltd. All rights reserved.
#
# This source code is licensed under the OSL-3.0 license found in the
# LICENSE file in the root directory of this source tree.
from django.conf.urls import url
from django.contrib.auth.decorators import login_required

from shuup_stripe import views

urlpatterns = [
    url(
        r"^customer/save-payment-info/$",
        login_required(views.StripeSavedPaymentInfoView.as_view()),
        name="stripe_saved_payment"
    ),url(
        r"^customer/create-payment-intent/$",
        login_required(views.StripeCreatePaymentIntentView.as_view()),
        name="stripe_create_payment_intent"
    ),
    url(
        r"^customer/delete-payment-info/$",
        login_required(views.StripeDeleteSavedPaymentInfoView.as_view()),
        name="stripe_delete_saved_payment"
    ),
    url(
        r"^order/pay/(?P<pk>.+?)/(?P<key>.+?)/$",
        views.StripePaymentView.as_view(),
        name="stripe_payment_view"
    )
]
