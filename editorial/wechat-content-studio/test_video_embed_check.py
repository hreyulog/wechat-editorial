import tempfile
import unittest
from pathlib import Path
from studio import write
from video_embed_check import verify_video_component, require_deliverable_video


class VideoEmbedTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        (self.folder/'src').mkdir(); (self.folder/'official').mkdir()
        write(self.folder/'src/channel.json', {'export_id': 'export/real-response', 'username': 'v2_test@finder'})
        self.article = {'channel_video': {'source': 'src/channel.json'}}

    def tearDown(self):
        self.temp.cleanup()

    def test_title_and_caption_do_not_prove_a_player(self):
        result = verify_video_component(self.folder, self.article, '<p>视频｜标题</p>')
        self.assertTrue(result['required']); self.assertFalse(result['preserved'])

    def test_expected_channel_id_and_author_must_match(self):
        for markup in ('<mp-common-videosnap data-id="export/other" data-username="v2_test@finder">',
                       '<mp-common-videosnap data-id="export/real-response" data-username="someone-else">'):
            self.assertFalse(verify_video_component(self.folder, self.article, markup)['preserved'])
        self.assertTrue(verify_video_component(self.folder, self.article,
            '<mp-common-videosnap data-id="export/real-response" data-username="v2_test@finder">')['preserved'])

    def test_video_id_in_plain_text_does_not_prove_an_iframe(self):
        write(self.folder/'src/video.json', {'vid': 'apiv_123'})
        article = {'video_embed': {'source': 'src/video.json'}}
        self.assertFalse(verify_video_component(self.folder, article, '<p>apiv_123</p><iframe src="other">')['preserved'])
        self.assertTrue(verify_video_component(self.folder, article, '<iframe data-mpvid="apiv_123">')['preserved'])

    def test_incomplete_or_stale_draft_cannot_be_delivered(self):
        write(self.folder/'official/receipt.json', {'manifest_sha256': 'same'})
        write(self.folder/'official/readback.json', {'news_item': [{'content': '<p>caption only</p>'}]})
        with self.assertRaisesRegex(ValueError, '视频尚未插入'):
            require_deliverable_video(self.folder, self.article, 'same')
        with self.assertRaisesRegex(ValueError, 'another content version'):
            require_deliverable_video(self.folder, self.article, 'different')

    def test_plain_articles_do_not_require_video_receipts(self):
        require_deliverable_video(self.folder, {}, 'irrelevant')

    def test_id_only_card_cannot_pass_delivery_even_if_the_id_matches(self):
        write(self.folder/'official/receipt.json', {'manifest_sha256':'same'})
        write(self.folder/'official/readback.json', {'news_item':[{'content':
            '<mp-common-videosnap data-id="export/real-response" data-username="v2_test@finder"></mp-common-videosnap>'}]})
        with self.assertRaisesRegex(ValueError,'仅有作品 ID'):
            require_deliverable_video(self.folder,self.article,'same')


if __name__ == '__main__':
    unittest.main()
