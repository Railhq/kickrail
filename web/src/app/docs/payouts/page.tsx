import type { Metadata } from "next";
import { C, H2, H3, List, Note, P, Snippet, Title } from "../ui";

export const metadata: Metadata = { title: "Paying affiliates" };

export default function Payouts() {
  return (
    <>
      <Title eyebrow="Running a program" lead="Kickrail works out who is owed what. You choose how the money moves: pay with the tools you already use and mark it done, send a PayPal batch from your own account, or fund one Stripe payout.">
        Paying affiliates
      </Title>

      <H2>Who is payable</H2>
      <P>An affiliate appears on the Payouts page when, for one currency:</P>
      <List>
        <li>they have pending commissions whose hold has ended,</li>
        <li>none of those are held for a self-referral review,</li>
        <li>the total, after any clawbacks, is above their campaign&apos;s minimum payout, and</li>
        <li>if you turned on &quot;Require a signed W-9 or W-8&quot;, they have submitted one. Affiliates without a form are listed but left out of every payout until they do.</li>
      </List>
      <P>Affiliates save where they want to be paid in their portal: a PayPal email, Wise, a bank account, or other instructions.</P>

      <H2>Ways to pay</H2>
      <H3>Pay yourself, then mark paid</H3>
      <List ordered>
        <li>On the Payouts page, download <b>due.csv</b>. It lists each affiliate&apos;s name, email, payout method and details, amount, currency and the number of commissions.</li>
        <li>Pay them however you normally do: PayPal, Wise, a bank transfer.</li>
        <li>Tick the affiliates you paid, add a reference (like a Wise batch id), and record the payout. Their commissions become <C>paid</C> and each affiliate gets an email, unless you turned payout emails off.</li>
      </List>
      <P>If you record one by mistake, <b>undo</b> it and the commissions go back to payable.</P>
      <Snippet label="due.csv">{`name,email,payout_method,payout_details,amount,currency,commissions
Jane Doe,jane@example.com,paypal,jane@example.com,145.00,USD,9
Ravi K,ravi@example.com,wise,ravi@example.com,60.00,USD,4`}</Snippet>
      <P>There is also a PayPal bulk payout CSV you can upload straight to PayPal&apos;s Payouts page.</P>

      <H3>PayPal Payouts from your account</H3>
      <P>Connect a PayPal REST app (client id and secret, sandbox or live) on the Payouts page. Kickrail then sends one PayPal batch from your PayPal balance to every payable affiliate who saved a PayPal email, and tracks each item until PayPal settles it. Failed items go back to payable.</P>

      <H3>Stripe payouts</H3>
      <P>On Growth and up, affiliates can connect a Stripe Express account from their portal. You pay one Stripe Checkout for the batch total and Kickrail transfers each affiliate&apos;s share from that payment. A failed transfer releases its commissions back into the payable pool.</P>
      <Note title="Availability">
        Stripe payouts are only shown when they are switched on for your Kickrail account. If you don&apos;t see the option on the Payouts page, use one of the methods above.
      </Note>

      <H2>Clawbacks</H2>
      <P>When a paid commission is refunded, the negative clawback is subtracted from the affiliate&apos;s next payout in the same currency. If the clawback is larger than what they are owed, they stay off the payable list until new commissions cover it.</P>
    </>
  );
}
