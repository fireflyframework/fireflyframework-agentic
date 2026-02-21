# Copyright 2026 Firefly Software Solutions Inc
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Security features for production deployments.

This module provides:
- **RBAC** (Role-Based Access Control) with JWT authentication
- **Encryption** for sensitive data at rest
- **SQL injection** prevention for database tools
"""

from fireflyframework_genai.security.encryption import AESEncryptionProvider, EncryptedMemoryStore, EncryptionProvider
from fireflyframework_genai.security.output_guard import OutputGuard, default_output_guard
from fireflyframework_genai.security.prompt_guard import PromptGuard, default_prompt_guard
from fireflyframework_genai.security.rbac import RBACManager, require_permission

__all__ = [
    "AESEncryptionProvider",
    "EncryptedMemoryStore",
    "EncryptionProvider",
    "OutputGuard",
    "PromptGuard",
    "RBACManager",
    "default_output_guard",
    "default_prompt_guard",
    "require_permission",
]
