// OFBiz-style Groovy service script: business logic the Java analyzer cannot see.
def orderId = parameters.orderId
def header = from("OrderHeader").where("orderId", orderId).queryOne()
if (header && header.grandTotal > 1000000) {
    return failure("Order ${orderId} needs manual fraud review")
}
return success()
