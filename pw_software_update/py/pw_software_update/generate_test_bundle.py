# Copyright 2021 The Pigweed Authors
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy of
# the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations under
# the License.
"""Script for generating test bundles"""

import argparse
import subprocess
import sys
from typing import Dict

from pw_software_update import dev_sign, keys, metadata, root_metadata
from pw_software_update.update_bundle_pb2 import UpdateBundle
from pw_software_update.tuf_pb2 import (RootMetadata, SignedRootMetadata,
                                        TargetsMetadata, SignedTargetsMetadata)

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization

HEADER = """// Copyright 2021 The Pigweed Authors
//
// Licensed under the Apache License, Version 2.0 (the "License"); you may not
// use this file except in compliance with the License. You may obtain a copy
// of the License at
//
//     https://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
// WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
// License for the specific language governing permissions and limitations under
// the License.

#pragma once

#include "pw_bytes/span.h"

"""

TEST_DEV_KEY = """-----BEGIN PRIVATE KEY-----
MIGHAgEAMBMGByqGSM49AgEGCCqGSM49AwEHBG0wawIBAQQgVgMQBOTJyx1xOafy
WTs2VkACf7Uo3RbP9Vun+oKXtMihRANCAATV7XJljxeUs2z2wqM5Q/kohAra1620
zXT90N9a3UR+IHksTd1OA7wFq220IQB/e4eVzbcOprN0MMMuSgXMxL8p
-----END PRIVATE KEY-----"""

TEST_PROD_KEY = """-----BEGIN PRIVATE KEY-----
MIGHAgEAMBMGByqGSM49AgEGCCqGSM49AwEHBG0wawIBAQQg73MLNmB/fPNX75Pl
YdynPtJkM2gGOWfIcHDuwuxSQmqhRANCAARpvjrXkjG2Fp+ZgREtxeTBBmJmWGS9
8Ny2tXY+Qggzl77G7wvCNF5+koz7ecsV6sKjK+dFiAXOIdqlga7p2j0A
-----END PRIVATE KEY-----"""

TEST_TARGETS_KEY = """-----BEGIN PRIVATE KEY-----
MIGHAgEAMBMGByqGSM49AgEGCCqGSM49AwEHBG0wawIBAQQggRCrido5vZOnkULH
sxQDt9Qoe/TlEKoqa1bhO1HFbi6hRANCAASVwdXbGWM7+f/r+Z2W6Dbd7CQA0Cbb
pkBv5PnA+DZnCkFhLW2kTn89zQv8W1x4m9maoINp9QPXQ4/nXlrVHqDg
-----END PRIVATE KEY-----"""


def byte_array_declaration(data: bytes, name: str) -> str:
    """Generates a byte C array declaration for a byte array"""
    type_name = '[[maybe_unused]] const std::byte'
    byte_str = ''.join([f'std::byte{{0x{b:02x}}},' for b in data])
    array_body = f'{{{byte_str}}}'
    return f'{type_name} {name}[] = {array_body};'


def proto_array_declaration(proto, name: str) -> str:
    """Generates a byte array declaration for a proto"""
    return byte_array_declaration(proto.SerializeToString(), name)


def private_key_pem_bytes(key: ec.EllipticCurvePrivateKey) -> bytes:
    """Serializes a private key in PEM format"""
    return key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo)


class Bundle:
    """A helper for test UpdateBundle generation"""
    def __init__(self):
        self._root_dev_key = serialization.load_pem_private_key(
            TEST_DEV_KEY.encode(), None)
        self._root_prod_key = serialization.load_pem_private_key(
            TEST_PROD_KEY.encode(), None)
        self._targets_key = serialization.load_pem_private_key(
            TEST_TARGETS_KEY.encode(), None)
        self._payloads: Dict[str, bytes] = {}
        self._version: int = 1

    def add_payload(self, name: str, payload: bytes) -> None:
        """Adds a payload to the bundle"""
        self._payloads[name] = payload

    def generate_dev_root_metadata(self) -> RootMetadata:
        """Generates a root metadata with the dev key"""
        return root_metadata.gen_root_metadata(
            root_metadata.RootKeys([private_key_pem_bytes(self._root_dev_key)
                                    ]),
            root_metadata.TargetsKeys(
                [private_key_pem_bytes(self._targets_key)]), self._version)

    def generate_prod_root_metadata(self) -> RootMetadata:
        """Generates a root metadata with the prod key"""
        return root_metadata.gen_root_metadata(
            root_metadata.RootKeys(
                [private_key_pem_bytes(self._root_prod_key)]),
            root_metadata.TargetsKeys(
                [private_key_pem_bytes(self._targets_key)]), self._version)

    def generate_dev_signed_root_metadata(self) -> SignedRootMetadata:
        """Generates a root metadata signed only by the dev key"""
        signed_root = SignedRootMetadata()
        root_metadata_proto = self.generate_dev_root_metadata()
        signed_root.serialized_root_metadata = \
            root_metadata_proto.SerializeToString()
        return dev_sign.sign_root_metadata(
            signed_root,
            self._root_dev_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption()))

    def generate_rotation_prod_signed_root_metadata(
            self,
            root_metadata_proto: RootMetadata = None) -> SignedRootMetadata:
        """Generates a root metadata signed by the prod key"""
        if not root_metadata_proto:
            root_metadata_proto = self.generate_prod_root_metadata()

        signed_root = SignedRootMetadata(
            serialized_root_metadata=root_metadata_proto.SerializeToString())

        for key in [self._root_dev_key, self._root_prod_key]:
            signature = keys.create_ecdsa_signature(
                signed_root.serialized_root_metadata,
                key.private_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PrivateFormat.PKCS8,
                    encryption_algorithm=serialization.NoEncryption()))
            signed_root.signatures.append(signature)

        return signed_root

    def generate_targets_metadata(self) -> TargetsMetadata:
        """Generates the targets metadata"""
        targets = metadata.gen_targets_metadata(self._payloads)
        return targets

    def generate_signed_targets_metadta(self) -> SignedTargetsMetadata:
        """Generate a signed metadata of a given role"""
        targets_metadata = self.generate_targets_metadata()
        return SignedTargetsMetadata(
            serialized_targets_metadata=targets_metadata.SerializeToString())

    def generate_bundle(
            self,
            signed_root_metadata: SignedRootMetadata = None) -> UpdateBundle:
        """Generate an update bundle"""
        bundle = UpdateBundle()

        if signed_root_metadata:
            bundle.root_metadata.CopyFrom(signed_root_metadata)

        bundle.targets_metadata['targets'].CopyFrom(
            self.generate_signed_targets_metadta())
        for name, payload in self._payloads.items():
            bundle.target_payloads[name] = payload

        return bundle


def parse_args():
    """Setup argparse."""
    parser = argparse.ArgumentParser()
    parser.add_argument("output_header",
                        help="output path of the generated C header")
    return parser.parse_args()


def main() -> int:
    """Main"""
    args = parse_args()

    test_bundle = Bundle()

    # Adds some update files.
    test_bundle.add_payload('file1', 'file 1 content'.encode())  # type: ignore
    test_bundle.add_payload('file2', 'file 2 content'.encode())  # type: ignore

    dev_signed_root = test_bundle.generate_dev_signed_root_metadata()
    dev_signed_bundle = test_bundle.generate_bundle(dev_signed_root)
    prod_signed_root = \
        test_bundle.generate_rotation_prod_signed_root_metadata()
    prod_signed_bundle = test_bundle.generate_bundle(prod_signed_root)

    # Generates a prod root metadata that fails signature verification against
    # the dev root (i.e. it has a bad dev signature).
    bad_dev_signature = test_bundle.generate_prod_root_metadata()
    signed_bad_dev_signature = \
        test_bundle\
            .generate_rotation_prod_signed_root_metadata(bad_dev_signature)
    # Compromises the first signature, which is dev signed.
    signed_bad_dev_signature.signatures[0].sig = b'1' * 64
    signed_bad_dev_signature_bundle = test_bundle.generate_bundle(
        signed_bad_dev_signature)

    # Generates a prod root metadtata that fails to verify itself (bad prod
    # signature).
    bad_prod_signature = test_bundle.generate_prod_root_metadata()
    signed_bad_prod_signature = \
        test_bundle\
            .generate_rotation_prod_signed_root_metadata(
                bad_prod_signature)
    # Compromises the second signature, which is prod signed.
    signed_bad_prod_signature.signatures[1].sig = b'1' * 64
    signed_bad_prod_signature_bundle = test_bundle.generate_bundle(
        signed_bad_prod_signature)

    with open(args.output_header, 'w') as header:
        header.write(HEADER)
        header.write(
            proto_array_declaration(dev_signed_bundle, 'kTestDevBundle'))
        header.write(proto_array_declaration(dev_signed_root,
                                             'kDevSignedRoot'))
        header.write(
            proto_array_declaration(prod_signed_bundle, 'kTestProdBundle'))
        header.write(
            proto_array_declaration(signed_bad_dev_signature_bundle,
                                    'kTestBadDevSignatureBundle'))
        header.write(
            proto_array_declaration(signed_bad_prod_signature_bundle,
                                    'kTestBadProdSignature'))

    subprocess.run([
        'clang-format',
        '-i',
        args.output_header,
    ], check=True)

    return 0


if __name__ == "__main__":
    sys.exit(main())
