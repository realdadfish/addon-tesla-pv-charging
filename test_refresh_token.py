#!/usr/bin/env python3 -u

import teslapy

with teslapy.Tesla(input("Your E-Mail: ")) as tesla:
    if not tesla.authorized:
        try:
            tesla.refresh_token(refresh_token = input("Your refresh token: "))
        except Exception as e:
            raise Exception("Refreshing the access token failed; is the refresh_token still valid?") from e
