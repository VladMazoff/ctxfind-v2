// Test JS module
import { User } from './models';

class UserManager {
    constructor() {
        this.users = [];
    }

    addUser(data) {
        const user = new User(data.name, data.email);
        this.users.push(user);
        return user;
    }

    findUser(email) {
        return this.users.find(u => u.email === email);
    }

    processUser(data) {
        return this.addUser(data);
    }
}

const manager = new UserManager();
export { UserManager };
