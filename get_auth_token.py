#!/usr/bin/env python3 -u

"""
Description Fetches the initial auth token for queries to the Tesla API. Enter this token in your options.json

@author: Thomas Keller
@copyright: Copyright (c) 2018, Siemens AG
@note:  All rights reserved.
"""

import teslapy
import sys

with teslapy.Tesla(input('Enter Tesla Login E-Mail: '), cache_loader=lambda: {}, cache_dumper=lambda x: None) as tesla:
    if not tesla.authorized:
        print('Use browser to login. Page Not Found will be shown at success.')
        print('Open this URL: ' + tesla.authorization_url())
        try:
            token = tesla.fetch_token(authorization_response=input('Enter URL after authentication: '))
            print(f"Refresh Token: {token['refresh_token']}")
        except Exception as e:
            print(f"Authorisation failed: {e}")
            sys.exit(1)
    else:
        print(f"Refresh Token: {tesla.token['refresh_token']}")