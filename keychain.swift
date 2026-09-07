import Foundation
import Security

// Secrets enter through stdin, never through process arguments or log output.
do {
    let input = FileHandle.standardInput.readDataToEndOfFile()
    let request = try JSONSerialization.jsonObject(with: input) as! [String: String]
    let account = request["account"] ?? "oauth"
    guard ["oauth", "client-secret", "keychain-test"].contains(account) else { exit(2) }
    let query: [String: Any] = [
        kSecClass as String: kSecClassGenericPassword,
        kSecAttrService as String: "cz.tesla-xbar",
        kSecAttrAccount as String: account
    ]
    var status: OSStatus
    switch request["operation"] {
    case "get":
        var readQuery = query
        readQuery[kSecReturnData as String] = true
        readQuery[kSecMatchLimit as String] = kSecMatchLimitOne
        var result: CFTypeRef?
        status = SecItemCopyMatching(readQuery as CFDictionary, &result)
        if status == errSecSuccess, let data = result as? Data {
            FileHandle.standardOutput.write(data)
        }
    case "set":
        guard let value = request["value"] else { exit(2) }
        let attributes: [String: Any] = [kSecValueData as String: Data(value.utf8)]
        status = SecItemUpdate(query as CFDictionary, attributes as CFDictionary)
        if status == errSecItemNotFound {
            var item = query.merging(attributes) { _, new in new }
            item[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
            status = SecItemAdd(item as CFDictionary, nil)
        }
    case "delete":
        status = SecItemDelete(query as CFDictionary)
    default:
        exit(2)
    }
    if status == errSecItemNotFound { exit(3) }
    if status != errSecSuccess {
        FileHandle.standardError.write(Data("Keychain error \(status)\n".utf8))
        exit(1)
    }
} catch {
    FileHandle.standardError.write(Data("Invalid Keychain request\n".utf8))
    exit(2)
}
