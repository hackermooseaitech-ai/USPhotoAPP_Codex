from allauth.socialaccount.providers.yahoo.provider import YahooProvider


class SafeYahooProvider(YahooProvider):
    def extract_common_fields(self, data):
        return {
            "email": data.get("email", ""),
            "last_name": data.get("family_name", ""),
            "first_name": data.get("given_name", ""),
            "name": data.get("name", ""),
        }
