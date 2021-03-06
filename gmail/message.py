import datetime
import email
import re
import time
import os
from email.header import decode_header, make_header
from imaplib import ParseFlags

class Message():


    def __init__(self, mailbox, uid):
        self.uid = uid
        self.mailbox = mailbox
        self.gmail = mailbox.gmail if mailbox else None

        self.message = None
        self.headers = {}

        self.subject = None
        self.body = None
        self.html = None

        self.to = None
        self.fr = None
        self.cc = None
        self.delivered_to = None

        self.sent_at = None

        self.flags = []
        self.labels = []

        self.thread_id = None
        self.thread = []
        self.message_id = None

        self.attachments = None



    def is_read(self):
        return (b'\\Seen' in self.flags)

    def read(self):
        flag = b'\\Seen'
        self.gmail.imap.uid('STORE', self.uid, b'+FLAGS', flag)
        if flag not in self.flags: self.flags.append(flag)

    def unread(self):
        flag = b'\\Seen'
        self.gmail.imap.uid('STORE', self.uid, b'-FLAGS', flag)
        if flag in self.flags: self.flags.remove(flag)

    def is_starred(self):
        return (b'\\Flagged' in self.flags)

    def star(self):
        flag = b'\\Flagged'
        self.gmail.imap.uid('STORE', self.uid, b'+FLAGS', flag)
        if flag not in self.flags: self.flags.append(flag)

    def unstar(self):
        flag = b'\\Flagged'
        self.gmail.imap.uid('STORE', self.uid, b'-FLAGS', flag)
        if flag in self.flags: self.flags.remove(flag)

    def is_draft(self):
        return (b'\\Draft' in self.flags)

    def has_label(self, label):
        full_label = '%s' % label
        return (full_label in self.labels)

    def add_label(self, label):
        full_label = '%s' % label
        self.gmail.imap.uid('STORE', self.uid, b'+X-GM-LABELS', full_label)
        if full_label not in self.labels: self.labels.append(full_label)

    def remove_label(self, label):
        full_label = '%s' % label
        self.gmail.imap.uid('STORE', self.uid, b'-X-GM-LABELS', full_label)
        if full_label in self.labels: self.labels.remove(full_label)


    def is_deleted(self):
        return ('\\Deleted' in self.flags)

    def delete(self):
        flag = '\\Deleted'
        self.gmail.imap.uid('STORE', self.uid, b'+FLAGS', flag)
        if flag not in self.flags: self.flags.append(flag)

        trash = b'[Gmail]/Trash' if b'[Gmail]/Trash' in self.gmail.labels() else b'[Gmail]/Bin'
        if self.mailbox.name not in [b'[Gmail]/Bin', b'[Gmail]/Trash']:
            self.move_to(trash)

    # def undelete(self):
    #     flag = '\\Deleted'
    #     self.gmail.imap.uid(b'STORE', self.uid, '-FLAGS', flag)
    #     if flag in self.flags: self.flags.remove(flag)


    def move_to(self, name):
        self.gmail.copy(self.uid, name, self.mailbox.name)
        if name not in [b'[Gmail]/Bin', b'[Gmail]/Trash']:
            self.delete()



    def archive(self):
        self.move_to(b'[Gmail]/All Mail')

    def parse_headers(self, message):
        hdrs = {}
        for hdr in list(message.keys()):
            hdrs[hdr] = message[hdr]
        return hdrs

    def parse_flags(self, headers):
        return list(ParseFlags(headers))
        # flags = re.search(rb'FLAGS \(([^\)]*)\)', headers).groups(1)[0].split(' ')

    def parse_labels(self, headers):
        if re.search(r'X-GM-LABELS \(([^\)]+)\)', headers):
            labels = re.search(r'X-GM-LABELS \(([^\)]+)\)', headers).groups(1)[0].split(' ')
            return [l.replace('"', '').decode("string_escape") for l in labels]
        else:
            return list()

    def parse_subject(self, encoded_subject):
        dh = decode_header(encoded_subject)
        default_charset = b'ASCII'
        return ''.join([ str(t[0], t[1] or default_charset) for t in dh ])

    def parse(self, raw_message):
        raw_headers = raw_message[0]
        raw_email = raw_message[1]

        self.message = email.message_from_string(raw_email)
        self.headers = self.parse_headers(self.message)

        self.to = self.message[b'to']
        self.fr = self.message[b'from']
        self.delivered_to = self.message[b'delivered_to']

        self.subject = self.parse_subject(self.message[b'subject'])

        if self.message.get_content_maintype() == "multipart":
            for content in self.message.walk():
                if content.get_content_type() == "text/plain":
                    self.body = content.get_payload(decode=True)
                elif content.get_content_type() == "text/html":
                    self.html = content.get_payload(decode=True)
        elif self.message.get_content_maintype() == "text":
            self.body = self.message.get_payload()

        self.sent_at = datetime.datetime.fromtimestamp(time.mktime(email.utils.parsedate_tz(self.message[b'date'])[:9]))

        self.flags = self.parse_flags(raw_headers)

        self.labels = self.parse_labels(raw_headers)

        if re.search(r'X-GM-THRID (\d+)', raw_headers):
            self.thread_id = re.search(r'X-GM-THRID (\d+)', raw_headers).groups(1)[0]
        if re.search(r'X-GM-MSGID (\d+)', raw_headers):
            self.message_id = re.search(r'X-GM-MSGID (\d+)', raw_headers).groups(1)[0]


        # Parse attachments into attachment objects array for this message
        self.attachments = []
        def make_attachement(attachments):
            for attachment in attachments:
                if attachment.get_content_type() == b'message/rfc822':
                    make_attachement(attachment.get_payload())
                else:
                    if not attachment.is_multipart():
                        self.attachments.append(Attachment(attachment))
                    else:
                        make_attachement(attachment.get_payload())

        make_attachement(self.message.get_payload())


    def fetch(self):
        if not self.message:
            response, results = self.gmail.imap.uid('FETCH', self.uid, b'(BODY.PEEK[] FLAGS X-GM-THRID X-GM-MSGID X-GM-LABELS)')

            self.parse(results[0])

        return self.message

    # returns a list of fetched messages (both sent and received) in chronological order
    def fetch_thread(self):
        self.fetch()
        original_mailbox = self.mailbox
        self.gmail.use_mailbox(original_mailbox.name)

        # fetch and cache messages from inbox or other received mailbox
        response, results = self.gmail.imap.uid('SEARCH', None, b'(X-GM-THRID ' + self.thread_id + ')')
        received_messages = {}
        uids = results[0].split(' ')
        if response == 'OK':
            for uid in uids: received_messages[uid] = Message(original_mailbox, uid)
            self.gmail.fetch_multiple_messages(received_messages)
            self.mailbox.messages.update(received_messages)

        # fetch and cache messages from b'sent'
        self.gmail.use_mailbox(b'[Gmail]/Sent Mail')
        response, results = self.gmail.imap.uid('SEARCH', None, b'(X-GM-THRID ' + self.thread_id + b')')
        sent_messages = {}
        uids = results[0].split(' ')
        if response == 'OK':
            for uid in uids: sent_messages[uid] = Message(self.gmail.mailboxes[b'[Gmail]/Sent Mail'], uid)
            self.gmail.fetch_multiple_messages(sent_messages)
            self.gmail.mailboxes[b'[Gmail]/Sent Mail'].messages.update(sent_messages)

        self.gmail.use_mailbox(original_mailbox.name)

        # combine and sort sent and received messages
        return sorted(list(dict(list(received_messages.items()) + list(sent_messages.items())).values()), key=lambda m: m.sent_at)


class Attachment:

    def __init__(self, attachment):
        self.name = attachment.get_filename()
        # Raw file data
        self.payload = attachment.get_payload(decode=True)
        # Filesize in kilobytes
        self.size = int(round(len(self.payload)/1000.0))

    def save(self, path=None):
        if path is None:
            # Save as name of attachment if there is no path specified
            path = self.name
        elif os.path.isdir(path):
            # If the path is a directory, save as name of attachment in that directory
            path = os.path.join(path, self.name)

        with open(path, 'wb') as f:
            f.write(self.payload)
