from flask import Flask, render_template, request, redirect,jsonify, url_for, flash
app = Flask(__name__)

from sqlalchemy import create_engine, asc
from sqlalchemy.orm import sessionmaker
from database_setup import Base, Restaurant, MenuItem,User
import random,string
from flask import session as login_session  
#Connect to Database and create database session
engine = create_engine('sqlite:///restaurantmenuwithusers.db')
Base.metadata.bind = engine

DBSession = sessionmaker(bind=engine)
session = DBSession()

#imports for gconnect resource
from oauth2client.client import flow_from_clientsecrets
from oauth2client.client import FlowExchangeError
import requests
import httplib2
import json
from flask import make_response
from functools import wraps

CLIENT_ID = json.loads(open('client_secrets.json','r').read())['web']['client_id']

# Create a state Token to prevent request forgery
@app.route('/login')
def showLogin():
    state = ''.join(random.choice(string.ascii_uppercase+string.digits) for x in range(32))
    login_session['state'] = state
    print 'Current session state is {STATE}'.format(STATE=state)
    return render_template("login.html",STATE=state)

@app.route('/fbconnect', methods=['POST'])
def fbconnect():
    if request.args.get('state') != login_session['state']:
        response = make_response(json.dumps('Invalid state parameter.'), 401)
        response.headers['Content-Type'] = 'application/json'
        return response
    access_token = request.data
    print "access token received %s " % access_token

    app_id = json.loads(open('fb_client_secrets.json', 'r').read())[
        'web']['app_id']
    app_secret = json.loads(
        open('fb_client_secrets.json', 'r').read())['web']['app_secret']
    url = 'https://graph.facebook.com/oauth/access_token?grant_type=fb_exchange_token&client_id=%s&client_secret=%s&fb_exchange_token=%s' % (
        app_id, app_secret, access_token)
    h = httplib2.Http()
    result = h.request(url, 'GET')[1]

    # Use token to get user info from API
    userinfo_url = "https://graph.facebook.com/v2.4/me"
    # strip expire tag from access token
    token = result.split("&")[0]


    url = 'https://graph.facebook.com/v2.4/me?%s&fields=name,id,email' % token
    h = httplib2.Http()
    result = h.request(url, 'GET')[1]
    # print "url sent for API access:%s"% url
    # print "API JSON result: %s" % result
    data = json.loads(result)
    login_session['provider'] = 'facebook'
    login_session['username'] = data["name"]
    login_session['email'] = data["email"]
    login_session['facebook_id'] = data["id"]

    # The token must be stored in the login_session in order to properly logout, let's strip out the information before the equals sign in our token
    stored_token = token.split("=")[1]
    login_session['access_token'] = stored_token

    # Get user picture
    url = 'https://graph.facebook.com/v2.4/me/picture?%s&redirect=0&height=200&width=200' % token
    h = httplib2.Http()
    result = h.request(url, 'GET')[1]
    data = json.loads(result)

    login_session['picture'] = data["data"]["url"]

    # see if user exists
    user_id = getUserID(login_session['email'])
    if not user_id:
        user_id = createUser(login_session)
    login_session['user_id'] = user_id

    output = ''
    output += '<h1>Welcome, '
    output += login_session['username']

    output += '!</h1>'
    output += '<img src="'
    output += login_session['picture']
    output += ' " style = "width: 300px; height: 300px;border-radius: 150px;-webkit-border-radius: 150px;-moz-border-radius: 150px;"> '

    flash("Now logged in as %s" % login_session['username'])
    return output


@app.route('/fbdisconnect')
def fbdisconnect():
    facebook_id = login_session['facebook_id']
    # The access token must me included to successfully logout
    access_token = login_session['access_token']
    url = 'https://graph.facebook.com/%s/permissions?access_token=%s' % (facebook_id,access_token)
    h = httplib2.Http()
    result = h.request(url, 'DELETE')[1]
    return "you have been logged out"

# gconnect
@app.route('/gconnect', methods=['POST'])
def gconnect():
    if request.args.get('state') != login_session['state']:
        response = make_response(json.dumps('Invalid state parameter'),401)
        response.headers['Content-Type'] = 'application/json'
        return response
    code = request.data
    try:
        # Upgrade the authorization code into a credentials object
        oauth_flow = flow_from_clientsecrets('client_secrets.json',scope='')
        oauth_flow.redirect_uri = 'postmessage'
        credentials = oauth_flow.step2_exchange(code)
        print credentials
    except FlowExchangeError:
        response = make_response(json.dumps('failed to upgrade the authorization code.'),401)
        response.headers['Content-Type'] = 'application/json'
        return response
    # check that access token is valid
    print "credentials:", credentials.to_json()
    access_token = credentials.access_token
    url = ('https://www.googleapis.com/oauth2/v1/tokeninfo?access_token={TOKEN}'.format(TOKEN=access_token))
    h = httplib2.Http()
    result = json.loads(h.request(url,'GET')[1])
    print 'result:',result
    # if there was an error in the access token info - abort
    if result.get('error') is not None:
        response = make_response(json.dumps(result.get('error')),500)
        response.headers['Content-Type'] = 'application/json'
        return response    
    # Verify that the access token is used for the intended user
    gplus_id = credentials.id_token['sub']
    if result['user_id'] != gplus_id:
        response = make_response(json.dumps("Token's user ID doesn't match given user ID."),401)
        response.headers['Content-Type'] = 'application/json'
        return response
    # Verify that the access token is valid for this app
    if result['issued_to'] != CLIENT_ID:
        response = make_response(json.dumps("Token's client doesn't match app's"),401)
        response.headers['Content-Type'] = 'application/json'
        return response

        
    # Check to see if user already logged in
    stored_credentials = login_session.get('credentials')
    stored_gplus_id = login_session.get('gplus_id')

    if stored_credentials is not None and gplus_id == stored_gplus_id:
        response = make_response(json.dumps('Current user is already logged in.'),200)
        response.headers['Content-Type'] = 'application/json'
        return make_response

    # Store the access token in the session for later use
    login_session['credentials'] = credentials
    login_session['gplus_id'] = gplus_id

    # Get user Info
    userinfo_url = "https://www.googleapis.com/oauth2/v1/userinfo"
    params = {'access_token': credentials.access_token,
                'alt': 'json'}
    answer = requests.get(userinfo_url,params=params)
    data = json.loads(answer.text)

    print "UserInfo",data
    if data.get("error") is not None:
        response = make_response(json.dumps(data.get('error').get('message')),500)
        response.headers['Content-Type'] = 'application/json'
        return response    
    login_session['username'] = data['name']
    login_session['picture'] = data['picture']
    login_session['email'] = data['email']
    user_id = getUserID(login_session['email'])
    # ADD PROVIDER TO LOGIN SESSION
    login_session['provider'] = 'google'
    if user_id is None:
        print "User not found - creating new one"
        user_id = createUser(login_session)
    login_session['user_id'] = user_id
    output = ''
    output +='<h1>Welcome, '
    output += login_session['username']
    output += '</h1>'
    output += '<img src="'
    output += login_session['picture']
    output += '" style="width: 300px; height: 300px; border-radius: 150px;-webkit-border-radius: 150px; -moz-border-radius:150px;">'
    flash('You are logged in as {NAME}'.format(NAME=login_session['username']))
    return output


# User Helper Functions


def createUser(login_session):
    newUser = User(name=login_session['username'], email=login_session[
                   'email'], picture=login_session['picture'])
    session.add(newUser)
    session.commit()
    user = session.query(User).filter_by(email=login_session['email']).one()
    # login_session['user_id'] = user_id
    return user.id


def getUserInfo(user_id):
    user = session.query(User).filter_by(id=user_id).one()
    return user


def getUserID(email):
    try:
        user = session.query(User).filter_by(email=email).one()
        return user.id
    except:
        return None


@app.route('/gdisconnect')
def gdisconnect():
    # Only disconnect  connected user
    credentials = login_session.get('credentials')
    if credentials is None:
        response = make_response(json.dumps("Current user not connected"),401)
        response.headers['Content-Type'] = "application/json"

    # Execute http get to revoke current token
    access_token = credentials.access_token
    print "access_token:",access_token
    url = 'https://accounts.google.com/o/oauth2/revoke?token={TOKEN}'.format(TOKEN=access_token)
    h = httplib2.Http()
    result = h.request(url,'GET')[0]
    # credentials.revoke(httplib2.Http())
    print "Revoke:", result
    if result['status'] == '200':
        del login_session['credentials']
        del login_session['gplus_id']
        if 'username' in login_session.keys():
            del login_session['username']
        del login_session['picture']
        del login_session['email']

        response = make_response(json.dumps("Subscriber successfully disconnected."),200)
        response.headers['Content-Type'] = 'application/json'

        return response
    else: 
        response = make_response(json.dumps(result),401)
        response.headers['Content-Type'] = 'application/json'
        return response


def requires_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if login_session.get('username',None) is None:   
            return redirect('/login')
        return f(*args, **kwargs)
    return decorated

# def authorized(f):
#     @wraps(f)
#     def decorated(*args, **kwargs):
#         if login_session.get('username',None) is None:   
#             return redirect('/login')
#         return f(*args, **kwargs)
#     return decorated

#JSON APIs to view Restaurant Information
@app.route('/restaurant/<int:restaurant_id>/menu/JSON')
def restaurantMenuJSON(restaurant_id):
    restaurant = session.query(Restaurant).filter_by(id = restaurant_id).one()
    items = session.query(MenuItem).filter_by(restaurant_id = restaurant_id).all()
    return jsonify(MenuItems=[i.serialize for i in items])


@app.route('/restaurant/<int:restaurant_id>/menu/<int:menu_id>/JSON')
def menuItemJSON(restaurant_id, menu_id):
    Menu_Item = session.query(MenuItem).filter_by(id = menu_id).one()
    return jsonify(Menu_Item = Menu_Item.serialize)

@app.route('/restaurant/JSON')
def restaurantsJSON():
    restaurants = session.query(Restaurant).all()
    return jsonify(restaurants= [r.serialize for r in restaurants])


#Show all restaurants
@app.route('/')
@app.route('/restaurant/')
def showRestaurants():
    restaurants = session.query(Restaurant).order_by(asc(Restaurant.name))
    if 'username' not in login_session:
        return render_template('publicrestaurants.html', restaurants = restaurants)
    else:    
        return render_template('restaurants.html', restaurants = restaurants)

#Create a new restaurant
@app.route('/restaurant/new/', methods=['GET','POST'])
@requires_auth
def newRestaurant():
    if request.method == 'POST':
        newRestaurant = Restaurant(name = request.form['name'],user_id=login_session['user_id'])
        session.add(newRestaurant)
        flash('New Restaurant %s Successfully Created' % newRestaurant.name)
        session.commit()
        return redirect(url_for('showRestaurants'))
    else:
        return render_template('newRestaurant.html')

#Edit a restaurant
@app.route('/restaurant/<int:restaurant_id>/edit/', methods = ['GET', 'POST'])
@requires_auth
def editRestaurant(restaurant_id):
    editedRestaurant = session.query(Restaurant).filter_by(id = restaurant_id).one()
    if editedRestaurant.user_id != login_session['user_id']:
        return "<script>function myFunction() {alert('You are not authorized to delete this restaurant. Please create your own restaurant in order to delete.');}</script><body onload='myFunction()''>"
    if request.method == 'POST':
        if request.form['name']:
            editedRestaurant.name = request.form['name']
            flash('Restaurant Successfully Edited %s' % editedRestaurant.name)
            return redirect(url_for('showRestaurants'))
    else:
        return render_template('editRestaurant.html', restaurant = editedRestaurant)


#Delete a restaurant
@app.route('/restaurant/<int:restaurant_id>/delete/', methods = ['GET','POST'])
@requires_auth
def deleteRestaurant(restaurant_id):
    restaurantToDelete = session.query(Restaurant).filter_by(id = restaurant_id).one()
    if restaurantToDelete.user_id != login_session['user_id']:
        return "<script>function myFunction() {alert('You are not authorized to delete this restaurant. Please create your own restaurant in order to delete.');}</script><body onload='myFunction()''>"
    if request.method == 'POST':
        session.delete(restaurantToDelete)
        flash('%s Successfully Deleted' % restaurantToDelete.name)
        session.commit()
        return redirect(url_for('showRestaurants', restaurant_id = restaurant_id))
    else:
        return render_template('deleteRestaurant.html',restaurant = restaurantToDelete)

#Show a restaurant menu
@app.route('/restaurant/<int:restaurant_id>/')
@app.route('/restaurant/<int:restaurant_id>/menu/')
def showMenu(restaurant_id):
    restaurant = session.query(Restaurant).filter_by(id = restaurant_id).one()
    creator = getUserInfo(restaurant.user_id)
    items = session.query(MenuItem).filter_by(restaurant_id = restaurant_id).all()
    if 'username' not in login_session or creator.id != login_session['user_id']:
        return render_template('publicmenu.html', items=items, restaurant=restaurant, creator=creator)
    else:
        return render_template('menu.html', items=items, restaurant=restaurant, creator=creator)

     


#Create a new menu item
@app.route('/restaurant/<int:restaurant_id>/menu/new/',methods=['GET','POST'])
@requires_auth
def newMenuItem(restaurant_id):
    restaurant = session.query(Restaurant).filter_by(id = restaurant_id).one()
    if request.method == 'POST':
        newItem = MenuItem(name = request.form['name'], description = request.form['description'], price = request.form['price'], course = request.form['course'], restaurant_id = restaurant_id,user_id=restaurant.user_id)
        session.add(newItem)
        session.commit()
        flash('New Menu %s Item Successfully Created' % (newItem.name))
        return redirect(url_for('showMenu', restaurant_id = restaurant_id))
    else:
        return render_template('newmenuitem.html', restaurant_id = restaurant_id)

#Edit a menu item
@app.route('/restaurant/<int:restaurant_id>/menu/<int:menu_id>/edit', methods=['GET','POST'])
@requires_auth
def editMenuItem(restaurant_id, menu_id):

    editedItem = session.query(MenuItem).filter_by(id = menu_id).one()
    restaurant = session.query(Restaurant).filter_by(id = restaurant_id).one()
    if restaurant.user_id != login_session['user_id']:
        return "<script>function myFunction() {alert('You are not authorized to edit menu items for this restaurant. Please create your own restaurant in order to delete.');}</script><body onload='myFunction()''>"
    if request.method == 'POST':
        if request.form['name']:
            editedItem.name = request.form['name']
        if request.form['description']:
            editedItem.description = request.form['description']
        if request.form['price']:
            editedItem.price = request.form['price']
        if request.form['course']:
            editedItem.course = request.form['course']
        session.add(editedItem)
        session.commit() 
        flash('Menu Item Successfully Edited')
        return redirect(url_for('showMenu', restaurant_id = restaurant_id))
    else:
        return render_template('editmenuitem.html', restaurant_id = restaurant_id, menu_id = menu_id, item = editedItem)


#Delete a menu item
@app.route('/restaurant/<int:restaurant_id>/menu/<int:menu_id>/delete', methods = ['GET','POST'])
@requires_auth
def deleteMenuItem(restaurant_id,menu_id):
    restaurant = session.query(Restaurant).filter_by(id = restaurant_id).one()
    if restaurant.user_id != login_session['user_id']:
        return "<script>function myFunction() {alert('You are not authorized to delete this menu item. Please create your own restaurant in order to delete.');}</script><body onload='myFunction()''>"
    itemToDelete = session.query(MenuItem).filter_by(id = menu_id).one() 
    if request.method == 'POST':
        session.delete(itemToDelete)
        session.commit()
        flash('Menu Item Successfully Deleted')
        return redirect(url_for('showMenu', restaurant_id = restaurant_id))
    else:
        return render_template('deleteMenuItem.html', item = itemToDelete)



# Disconnect based on provider
@app.route('/disconnect')
def disconnect():
    if 'provider' in login_session:
        if login_session['provider'] == 'google':
            gdisconnect()
            del login_session['gplus_id']
            del login_session['credentials']
        if login_session['provider'] == 'facebook':
            fbdisconnect()
            del login_session['facebook_id']
        del login_session['username']
        del login_session['email']
        del login_session['picture']
        del login_session['user_id']
        del login_session['provider']
        flash("You have successfully been logged out.")
        return redirect(url_for('showRestaurants'))
    else:
        flash("You were not logged in")
        return redirect(url_for('showRestaurants'))



if __name__ == '__main__':
    app.secret_key = 'super_secret_key'
    app.debug = True
    app.run(host = '0.0.0.0', port = 5000)
