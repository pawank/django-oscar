from django.contrib import messages
from django import http
from django.core.urlresolvers import reverse
from django.utils.translation import ugettext_lazy as _
from datacash.facade import Facade

from oscar.apps.checkout import views, exceptions
from oscar.apps.payment.forms import BankcardForm
from oscar.apps.payment.models import SourceType
from oscar.apps.order.models import BillingAddress

from .forms import BillingAddressForm

from django.shortcuts import redirect
from django.views import generic
from oscar.apps.shipping.methods import NoShippingRequired
from oscar.core.loading import get_class, get_classes

CheckoutSessionMixin = get_class('checkout.session', 'CheckoutSessionMixin')
class PaymentMethodView(CheckoutSessionMixin, generic.TemplateView):
    """
    View for a user to choose which payment method(s) they want to use.

    This would include setting allocations if payment is to be split
    between multiple sources. It's not the place for entering sensitive details
    like bankcard numbers though - that belongs on the payment details view.
    """
    pre_conditions = [
        'check_basket_is_not_empty',
        'check_basket_is_valid',
        'check_user_email_is_captured',
        'check_shipping_data_is_captured']
    skip_conditions = ['skip_unless_payment_is_required']

    def get(self, request, *args, **kwargs):
        print "PaymentMethodView"
        # By default we redirect straight onto the payment details view. Shops
        # that require a choice of payment method may want to override this
        # method to implement their specific logic.
        session_payment_option = request.session.get("payment_options", None)
        print "payment_options = %s" % session_payment_option

        #if session_payment_option is None:
        return self.get_success_response()
        #else:
        #    return redirect('checkout:payment-details')

    def get_success_response(self):
        print "PaymentMethodView success"
        return redirect('checkout:select-payment')

# Customise the core PaymentDetailsView to integrate Datacash
class PaymentDetailsView(views.PaymentDetailsView):
    template_name = "checkout/select_payment.html"
    def check_payment_data_is_captured(self, request):
        if request.method != "POST":
            raise exceptions.FailedPreCondition(
                url=reverse('checkout:payment-details'),
                message=_("Please enter your payment details"))

    def get_context_data(self, **kwargs):
        print "get_context_data"
        ctx = super(PaymentDetailsView, self).get_context_data(**kwargs)
        # Ensure newly instantiated instances of the bankcard and billing
        # address forms are passed to the template context (when they aren't
        # already specified).
        if 'bankcard_form' not in kwargs:
            ctx['bankcard_form'] = BankcardForm()
        if 'billing_address_form' not in kwargs:
            ctx['billing_address_form'] = self.get_billing_address_form(
                ctx['shipping_address']
            )
        elif kwargs['billing_address_form'].is_valid():
            # On the preview view, we extract the billing address into the
            # template context so we can show it to the customer.
            ctx['billing_address'] = kwargs[
                'billing_address_form'].save(commit=False)
        return ctx


    def get_billing_address_form(self, shipping_address):
        """
        Return an instantiated billing address form
        """
        addr = self.get_default_billing_address()
        if not addr:
            return BillingAddressForm(shipping_address=shipping_address)
        billing_addr = BillingAddress()
        addr.populate_alternative_model(billing_addr)
        return BillingAddressForm(shipping_address=shipping_address,
                                  instance=billing_addr)

    def handle_payment_details_submission(self, request):
        print "handle_payment_details_submission"
        # Validate the submitted forms
        bankcard_form = BankcardForm(request.POST)
        shipping_address = self.get_shipping_address(
            self.request.basket)
        address_form = BillingAddressForm(shipping_address, request.POST)

        if address_form.is_valid() and bankcard_form.is_valid():
            # If both forms are valid, we render the preview view with the
            # forms hidden within the page. This seems odd but means we don't
            # have to store sensitive details on the server.
            return self.render_preview(
                request, bankcard_form=bankcard_form,
                billing_address_form=address_form)

        # Forms are invalid - show them to the customer along with the
        # validation errors.
        return self.render_payment_details(
            request, bankcard_form=bankcard_form,
            billing_address_form=address_form)

    def handle_place_order_submission(self, request):
        print "handle_place_order_submission"
        bankcard_form = BankcardForm(request.POST)
        shipping_address = self.get_shipping_address(
            self.request.basket)
        address_form = BillingAddressForm(shipping_address, request.POST)
        print bankcard_form
        print shipping_address
        print address_form
        if address_form.is_valid() and bankcard_form.is_valid():
            # Forms still valid, let's submit an order
            submission = self.build_submission(
                order_kwargs={
                    'billing_address': address_form.save(commit=False),
                },
                payment_kwargs={
                    'bankcard_form': bankcard_form,
                    'billing_address_form': address_form
                }
            )
            return self.submit(**submission)

        # Must be DOM tampering as these forms were valid and were rendered in
        # a hidden element.  Hence, we don't need to be that friendly with our
        # error message.
        messages.error(request, _("Invalid submission"))
        return http.HttpResponseRedirect(
            reverse('checkout:payment-details'))

    def handle_payment(self, order_number, total, **kwargs):
        print "handle_payment"
        # Make request to DataCash - if there any problems (eg bankcard
        # not valid / request refused by bank) then an exception would be
        # raised and handled by the parent PaymentDetail view)
        print "Order # %s" % order_number
        print "Total amount # %s" % total

        facade = Facade()
        bankcard = kwargs['bankcard_form'].bankcard
        datacash_ref = facade.pre_authorise(
            order_number, total.incl_tax, bankcard)

        # Request was successful - record the "payment source".  As this
        # request was a 'pre-auth', we set the 'amount_allocated' - if we had
        # performed an 'auth' request, then we would set 'amount_debited'.
        source_type, _ = SourceType.objects.get_or_create(name='Datacash')
        source = source_type.sources.model(
            source_type=source_type,
            currency=total.currency,
            amount_allocated=total.incl_tax,
            reference=datacash_ref)
        self.add_payment_source(source)

        # Also record payment event
        self.add_payment_event(
            'pre-auth', total.incl_tax, reference=datacash_ref)

    def post(self, request, *args, **kwargs):
        print "checkout_post"
        return self.handle_payment_details_submission(request)

def checkoutPayments(request):
        print "checkout payments"
        if request.method == "POST":
            payment_option = request.POST.get('payment_options', '')
            print "Payment option: %s" % payment_option
            session_payment_option = request.session.get("payment_options", None)
            print "payment_options = %s" % session_payment_option

            if request.POST.get('action', '') == '' and session_payment_option is None:
                print "action = ''"
                if len(payment_option) > 0:
                    request.session["payment_options"] = payment_option

                if payment_option == "cod":
                    print "COD"
                    pass
                elif payment_option == "bank":
                    #TODO
                    pass
                elif payment_option == "paypal":
                    print "Found paypal"
                    return http.HttpResponseRedirect(
                        reverse('paypal-redirect'))
                elif payment_option == "cc":
                    print "CC"
                    return http.HttpResponseRedirect(
                            reverse('checkout:payment-details'))
                else:
                    pass

        return redirect('/checkout/payment-method/')

