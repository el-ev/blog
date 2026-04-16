#import "../../driver/template.typ": info

#let title = "kioubit.dn42 Crypto #2 Part 1 Write-up"

#let content = [
  *Challenge:* #link("http://kioubit.dn42/challenge/ch2/")

  #info[
    *Note:* This challenge is hosted on the #link("https://dn42.dev/")[dn42] network.
    You may need a peering connection or a VPN tunnel into dn42 to access the link above.
  ]

  = At first glance

  The challenge presents a custom CAPTCHA. When it is activated, the frontend JavaScript loads a session from:

  - `api/getSessionForUser?username=guest&is_guest=true`

  and then verifies it with:

  - `api/checkSolution?session=...&solution=...`

  A sample session looked like this, with the ciphertext abbreviated for readability:

  ```json
  {
    "Captcha": "🐈 + 44455",
    "SessionData": {
      "Encrypted": "tWY4tD...qGb9mdkz7",
      "Metadata": "JmNhcHRjaGFfaW5kZXg9OSZpc192ZXJpZmllZD1mYWxzZQ=="
    },
    "SessionDataHmac": "PGq09Z41GoVbhFr6fsoubxQHrSc7+wAlwubzYXPktCA="
  }
  ```

  The base64-decoded metadata is:

  ```txt
  &captcha_index=9&is_verified=false
  ```

  At this stage, the obvious ideas were:
  + try to get a session with `is_guest=false`.
  + tamper with `is_verified` in the metadata.
  + replace `Captcha` with a trivial one.

  None of these worked.
  + the server responds with "You are only allowed to create guest sessions using this api endpoint".
  + `MAC authentication failed`.
  + whether the CAPTCHA is modified or not, the server returns `Incorrect captcha solution`.

  The `captcha.js` file contains a hint:
  #quote[A cryptographic solution is required which involves looking through the protocol used to verify the captcha response]

  // #pagebreak(weak: true)
  = Looking into the encryption scheme

  I created several sessions with different usernames and compared the `Encrypted` fields. Some examples are listed below:

  #table(
    columns: 2,
    [username], [Encrypted],
    [`a`], [`tWY4...c4z5rJtOHe7Mqm267...oSIL5wamyo4=`],
    [`b`], [`tWY4...c4z4zmzRkkePoAAFU...oSIL5wamyo4=`],
    [`aa`], [`tWY4...c4z4xyzyxFwktLoup...SL+TLJpOp6c=`],
    [`aaaaaaaaaaaaaaaaaaaaaaaaaa`], [`tWY4...c4zwQ...AnNWK...FYlLmh...`],
    [`aaaaaaaaaaaaaaabaaaaaaaaaa`], [`tWY4...c4zwQ...AnMvM...atjLmh...`],
  )

  Observations:
  + The first block was the same for all usernames.
  + Some trailing blocks were identical when username length was the same.
  + Changing a part of the username only affected certain blocks.

  These observations suggest that the plaintext is encrypted in ECB mode, with a structure something like this:

  ```txt
  prefix | username | suffix
  ```

  = Recovering the suffix

  Since the prefix and suffix are constant and the username is arbitrary, we can use a classic byte-at-a-time attack to recover the suffix.

  ```txt
  &source=web&solution=12513026260501710149&guest_account=true
  ```

  #info[
    *Note:* The solution changes over time, although I do not know how often or what triggers the change. Solve your own session to get the current solution.
  ]

  = Getting on the leaderboard

  Once the hidden solution was recovered, the rest was simple:
  + Request a fresh session for the scoreboard name.
  + Submit the value to `checkSolution`.

  The server returned a new verified session with `is_verified=true`.

  Using that session with `api/controlPanel` returned:

  ```text
  OK - Logged in as guest user
  Congratulations. You partially solved the challenge!
  Username: Iris
  Your username has been added to the leaderboard
  ```

  And that is the end of the story.
]

#if sys.inputs.at("with_driver", default: "false") == "false" {
  import "../../driver/template.typ": article
  show: article.with(title: title)
  content
}
