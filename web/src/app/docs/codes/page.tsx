import type { Metadata } from "next";
import Link from "next/link";
import { C, H2, List, Note, P, Snippet, Title } from "../ui";

export const metadata: Metadata = { title: "Creator codes" };

export default function Codes() {
  return (
    <>
      <Title eyebrow="Running a program" lead="A creator code is a word like JANE20 that a podcast listener or video viewer types at checkout. It gives them a discount and credits the affiliate, with no click and no cookie. Creator codes need the Starter plan or higher.">
        Creator codes
      </Title>

      <H2>How they work</H2>
      <P>Kickrail turns each affiliate&apos;s code into a real Stripe <b>promotion code</b> on your Stripe account, attached to a coupon you choose. When a customer redeems it in Stripe Checkout, the checkout session (and every invoice after it) carries that promotion code, and Kickrail credits the affiliate who owns it. It works even if the customer never visited your site through a link.</P>

      <H2>Set it up</H2>
      <List ordered>
        <li>In Stripe, create the coupon you want codes to give, for example 20% off for 3 months. Copy its id.</li>
        <li>In Kickrail, open Campaigns, edit the campaign and paste the coupon id into <b>Stripe coupon</b>.</li>
        <li>Give each affiliate on that campaign a code from their page under Affiliates (or with <C>code</C> on the <Link className="link" href="/docs/api#post-v1-affiliates">affiliates API</Link>). Kickrail creates the promotion code in Stripe right away.</li>
        <li>Make sure your checkout accepts codes: <C>allow_promotion_codes: true</C> on Checkout sessions you create, or &quot;Allow promotion codes&quot; on a Payment Link.</li>
      </List>
      <Snippet label="Node">{`stripe.checkout.sessions.create({
  mode: "subscription",
  line_items: [{ price: "price_pro_month", quantity: 1 }],
  allow_promotion_codes: true,          // customers can type JANE20
  client_reference_id: req.cookies.kr_ref, // and links still work too
  success_url: "https://yourapp.com/welcome",
});`}</Snippet>
      <P>An affiliate&apos;s portal shows each code and whether it is redeemable at checkout. In the API, the affiliate object has <C>code_redeemable_at_checkout</C> and a <C>codes</C> list.</P>

      <H2>Codes without a coupon</H2>
      <P>If the campaign has no Stripe coupon, the code is still saved and still credits the affiliate, but only when your own signup form collects it. Pass it as <C>code</C> to <Link className="link" href="/docs/server">POST /v1/referrals</Link>. Stripe won&apos;t accept it at checkout.</P>

      <H2>Rules</H2>
      <List>
        <li>Codes are 3 to 20 letters and digits, unique within the program.</li>
        <li>An affiliate can have more than one code; all of them credit the same affiliate.</li>
        <li>If someone was already referred by a link, a code from a different affiliate does not take them: the first referral wins. Under last-touch attribution the code moves them, until their first payment.</li>
        <li>Changing a code creates a new Stripe promotion code and the old one stops crediting the affiliate. Stripe keeps the old one active, so archive it there if it shouldn&apos;t give a discount any more.</li>
      </List>
      <Note title="If Stripe refuses the code">
        Stripe rejects a promotion code that already exists on your account or a coupon that has expired. The code is saved in Kickrail anyway and you see Stripe&apos;s reason when you save, so you can fix it in Stripe and save again.
      </Note>
    </>
  );
}
