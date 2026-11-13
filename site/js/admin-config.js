// The admin login (Amazon Cognito, managed login). These are public identifiers, not secrets:
// a browser app can't keep a secret, so the login is protected with PKCE instead.
// Values come from Terraform: `terraform output cognito_client_id` and the user pool domain.
export const COGNITO = {
  domain: "https://cwtch-and-cake-admin.auth.eu-west-2.amazoncognito.com",
  clientId: "43kb9ss79ubv1ffmvqv18m4tbb",
};
