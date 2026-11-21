import json
from zipfile import ZipFile


def write_demo(path):
    """Create a fictional archive for the demo and end-to-end evaluation."""
    streams = [
        {"ts": f"2026-10-{day:02}T{hour:02}:00:00Z", "conn_country": "IN",
         "ip_addr": "192.0.2.1", "master_metadata_album_artist_name": artist}
        for day, hour, artist in [
            (1, 18, "Juniper Circuit"), (2, 18, "Juniper Circuit"), (3, 19, "Pocket Atlas"),
            (4, 18, "Juniper Circuit"), (5, 19, "Pocket Atlas"), (6, 7, "Moon Arcade"),
        ]
    ]
    with ZipFile(path, "w") as archive:
        archive.writestr("Takeout/Location History/Records.json", json.dumps({
            "locations": [{"latitudeE7": 123456789, "longitudeE7": 765432100}] * 12
        }))
        archive.writestr("Takeout/My Activity/YouTube/MyActivity.html",
                         '<div class="outer-cell">Synthetic watch activity</div>' * 7)
        archive.writestr("Takeout/Contacts/All Contacts/All Contacts.vcf",
                         "BEGIN:VCARD\nFN:Sample Person\nEND:VCARD\n" * 4)
        archive.writestr("instagram/connections/followers_and_following/followers_1.json",
                         json.dumps([{"string_list_data": [{"value": "sample_account"}]}] * 8))
        archive.writestr("instagram/connections/contacts/synced_contacts.json",
                         json.dumps({"contacts_contact_info": [{"string_map_data": {"Name": "Sample"}}] * 3}))
        archive.writestr("instagram/messages/inbox/fictional/message_1.json",
                         json.dumps({"messages": [{"content": "Fictional message"}] * 5}))
        archive.writestr("instagram/ads_information/ad_topics.json", json.dumps({"topics": ["Fictional ad topic"]}))
        archive.writestr("Spotify/Streaming_History_Audio_2026_0.json", json.dumps(streams))
        archive.writestr("Spotify/Inferences.json", json.dumps({"inferences": ["Fictional segment"]}))
