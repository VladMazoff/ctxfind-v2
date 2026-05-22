/**
 * User manager module
 */

class UserManager {
    constructor() {
        this.users = [];
    }

    addUser(userData) {
        const user = new User(userData);
        this.users.push(user);
        return user;
    }

    findUserByEmail(email) {
        return this.users.find(u => u.email === email);
    }

    validateUser(user) {
        return user.name && user.email.includes('@');
    }
}

function createUserManager() {
    return new UserManager();
}

module.exports = { UserManager, createUserManager };